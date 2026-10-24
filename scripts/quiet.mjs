// Run a command; print one OK line on success, or only the last 40 lines on failure.
// Keeps lint/type-check/build output out of agent context: `node scripts/quiet.mjs <cmd> [args...]`.
import { spawnSync } from "node:child_process";

const [cmd, ...args] = process.argv.slice(2);
const res = spawnSync(cmd, args, { shell: true, encoding: "utf8" });
const label = [cmd, ...args].join(" ");
if (res.status === 0) {
  console.log(`OK  ${label}`);
} else {
  const out = `${res.stdout ?? ""}${res.stderr ?? ""}`.trim().split(/\r?\n/);
  console.log(`FAIL (${res.status})  ${label}\n${out.slice(-40).join("\n")}`);
}
process.exit(res.status ?? 1);
