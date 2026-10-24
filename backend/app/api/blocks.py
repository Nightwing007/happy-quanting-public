"""The block editor's backend: the palette, compiling a graph to strategy source, and each
person's custom blocks. Everything needs a login; custom blocks and graphs are the owner's alone."""

from dataclasses import replace
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from app import clock
from app.algos.api import Param
from app.algos.blocks import custom
from app.algos.blocks.catalog import CATALOG, BlockSpec
from app.algos.blocks.compile import (
    CompilerBug,
    GraphInvalid,
    GraphProblem,
    compile_graph,
    graph_has_code_blocks,
    node_values,
    validate_custom,
    validate_graph,
    warmup_for,
)
from app.algos.sandbox import run_in_subprocess
from app.algos.validate import validate_and_dry_run
from app.api.deps import CurrentUser, DbSession
from app.models import CustomBlock
from app.schemas import (
    AlgoParamOut,
    BlockCatalogOut,
    BlockOut,
    BlockPortOut,
    BlockProblemOut,
    CompileIn,
    CompileOut,
    CustomBlockIn,
    CustomBlockOut,
)

router = APIRouter(prefix="/api/blocks", tags=["blocks"])


def _plain(value):
    return f"{value:f}" if hasattr(value, "is_finite") else value


def _param_out(name: str, param: Param) -> AlgoParamOut:
    return AlgoParamOut(
        name=name,
        label=param.label or name.replace("_", " ").capitalize(),
        kind=param.kind,  # type: ignore[arg-type]
        default=_plain(param.default),
        min=_plain(param.min),
        max=_plain(param.max),
        choices=list(param.choices),
        help=param.help,
    )


def _ports(ports) -> list[BlockPortOut]:
    return [BlockPortOut(name=p.name, type=p.type, multi=p.multi, min=p.min) for p in ports]  # type: ignore[arg-type]


def _block_out(spec: BlockSpec) -> BlockOut:
    return BlockOut(
        type=spec.type,
        category=spec.category,  # type: ignore[arg-type]
        label=spec.label,
        help=spec.help,
        params=[_param_out(n, p) for n, p in spec.params.items()],
        inputs=_ports(spec.inputs),
        outputs=_ports(spec.outputs),
        lookback=spec.lookback,
        custom_id=spec.custom_id,
        custom_kind=spec.custom_kind,  # type: ignore[arg-type]
    )


def _entry(row: CustomBlock) -> dict:
    return {"type": f"custom:{row.id}", "name": row.name, "kind": row.kind, "definition": row.definition}


def _custom_out(row: CustomBlock) -> CustomBlockOut:
    return CustomBlockOut(
        id=row.id,
        type=f"custom:{row.id}",
        name=row.name,
        kind=row.kind,  # type: ignore[arg-type]
        definition=row.definition,
        created_at=row.created_at,
    )


def _owned(db, block_id: int, user_id: int) -> CustomBlock:
    row = db.get(CustomBlock, block_id)
    if row is None or row.owner_user_id != user_id:
        raise HTTPException(status_code=404, detail=f"There is no custom block {block_id}.")
    return row


def resolve_graph(db, user_id: int, graph: dict[str, Any]) -> dict[str, Any]:
    """The graph with the current definition of every custom block it uses that the user owns
    (a copy). Definitions the graph already carries for blocks no longer in the library stay, so a
    saved algorithm still compiles after its block was deleted."""
    entries: dict[str, dict] = {}
    for item in graph.get("custom_blocks") or []:
        if isinstance(item, dict) and isinstance(item.get("type"), str):
            entries[item["type"]] = item
    for node in graph.get("nodes") or []:
        kind = node.get("type") if isinstance(node, dict) else None
        if isinstance(kind, str) and kind.startswith("custom:") and kind[7:].isdigit():
            row = db.get(CustomBlock, int(kind[7:]))
            if row is not None and row.owner_user_id == user_id:
                entries[kind] = _entry(row)
    return {**graph, "custom_blocks": [entries[k] for k in sorted(entries)]}


def _problem_out(p: GraphProblem) -> BlockProblemOut:
    return BlockProblemOut(node_id=p.node_id, message=p.message)


def compile_for_user(
    db, user_id: int, graph: dict[str, Any], name: str, description: str, *, play: bool = False
) -> tuple[dict[str, Any], list[BlockProblemOut], str]:
    """(the graph with its custom blocks filled in, problems, source). `play` also plays the
    result over made-up prices when the graph holds code blocks, so a runtime error in one is found."""
    graph = resolve_graph(db, user_id, graph)
    problems = validate_graph(graph)
    if problems:
        return graph, [_problem_out(p) for p in problems], ""
    try:
        source = compile_graph(graph, name, description)
    except GraphInvalid as why:  # cannot happen after validate_graph; kept so a bug reads as one
        return graph, [_problem_out(p) for p in why.problems], ""
    except CompilerBug as why:
        raise HTTPException(status_code=500, detail=str(why)) from why
    if play and graph_has_code_blocks(graph):
        report = validate_and_dry_run(source, runner=run_in_subprocess)
        if not report.ok:
            found = [
                BlockProblemOut(line=p.line, col=p.col, code=p.code, message=p.message)
                for p in report.problems
            ]
            return graph, found, ""
    return graph, [], source


@router.get("/catalog", response_model=BlockCatalogOut)
def catalog(db: DbSession, user: CurrentUser):
    blocks = [_block_out(spec) for spec in CATALOG.values()]
    rows = db.scalars(
        select(CustomBlock).where(CustomBlock.owner_user_id == user.id).order_by(CustomBlock.id)
    )
    for row in rows:
        try:
            spec = custom.custom_spec(_entry(row), node_values)
        except ValueError:
            continue  # a damaged block is left out of the palette; the owner can still open and fix it
        blocks.append(_block_out(replace(spec, custom_id=row.id)))
    return BlockCatalogOut(blocks=blocks)


@router.post("/compile", response_model=CompileOut)
def compile_blocks(body: CompileIn, db: DbSession, user: CurrentUser):
    graph, problems, source = compile_for_user(
        db, user.id, body.graph, body.name, body.description, play=True
    )
    return CompileOut(
        ok=not problems, problems=problems, source=source, warmup_bars=0 if problems else warmup_for(graph)
    )


# --- custom blocks -----------------------------------------------------------------------


def _checked(body: CustomBlockIn) -> None:
    problems = validate_custom(body.kind, body.name, body.definition, runner=run_in_subprocess)
    if problems:
        raise HTTPException(
            status_code=400,
            detail="This block can't be saved: " + " ".join(p.message for p in problems),
        )


@router.get("/custom", response_model=list[CustomBlockOut])
def list_custom(db: DbSession, user: CurrentUser):
    rows = db.scalars(
        select(CustomBlock).where(CustomBlock.owner_user_id == user.id).order_by(CustomBlock.id)
    )
    return [_custom_out(r) for r in rows]


@router.post("/custom", response_model=CustomBlockOut)
def create_custom(body: CustomBlockIn, db: DbSession, user: CurrentUser):
    _checked(body)
    row = CustomBlock(
        owner_user_id=user.id,
        name=body.name,
        kind=body.kind,
        definition=body.definition,
        created_at=clock.now(),
    )
    db.add(row)
    db.commit()
    return _custom_out(row)


@router.get("/custom/{block_id}", response_model=CustomBlockOut)
def get_custom(block_id: int, db: DbSession, user: CurrentUser):
    return _custom_out(_owned(db, block_id, user.id))


@router.put("/custom/{block_id}", response_model=CustomBlockOut)
def update_custom(block_id: int, body: CustomBlockIn, db: DbSession, user: CurrentUser):
    row = _owned(db, block_id, user.id)
    _checked(body)
    row.name, row.kind, row.definition = body.name, body.kind, body.definition
    db.commit()
    return _custom_out(row)


@router.delete("/custom/{block_id}", status_code=204)
def delete_custom(block_id: int, db: DbSession, user: CurrentUser):
    db.delete(_owned(db, block_id, user.id))
    db.commit()
    return Response(status_code=204)
