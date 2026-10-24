"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

/** Names the algorithm before its first save. `onSave` reports a failure through `error`. */
export function SaveAlgoDialog({
  initialName,
  initialDescription,
  publishing,
  pending,
  error,
  onSave,
  onClose,
}: {
  initialName: string;
  initialDescription: string;
  publishing: boolean;
  pending: boolean;
  error: string | null;
  onSave: (name: string, description: string) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState(initialName);
  const [description, setDescription] = useState(initialDescription);

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim() && !pending) onSave(name, description);
          }}
          className="grid gap-4"
        >
          <DialogHeader>
            <DialogTitle>{publishing ? "Save, then publish" : "Save to My algorithms"}</DialogTitle>
            <DialogDescription>
              Keeps this code under My algorithms, where you can reopen it in the editor.
              {publishing ? " Next you choose how to list it in the marketplace." : ""}
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-1.5">
            <Label htmlFor="ed-save-name">Name</Label>
            <Input id="ed-save-name" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} autoFocus />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="ed-save-description">Description (optional)</Label>
            <Textarea
              id="ed-save-description"
              value={description}
              maxLength={500}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button type="submit" disabled={!name.trim() || pending}>
              {pending ? "Saving..." : publishing ? "Save and continue" : "Save"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
