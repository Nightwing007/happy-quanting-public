"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { UserAvatar } from "@/components/user-avatar";
import { useMe, useUpdateMe } from "@/lib/queries";
import type { User } from "@/lib/types";

function ProfileForm({ user }: { user: User }) {
  const update = useUpdateMe();
  const [displayName, setDisplayName] = useState(user.display_name);
  const [bio, setBio] = useState(user.bio);
  const [avatarUrl, setAvatarUrl] = useState(user.avatar_url ?? "");

  function submit(e: React.FormEvent) {
    e.preventDefault();
    update.mutate(
      { display_name: displayName.trim(), bio, avatar_url: avatarUrl.trim() || null },
      { onSuccess: () => toast.success("Profile saved.") },
    );
  }

  return (
    <Card className="mx-auto w-full max-w-lg">
      <CardHeader>
        <CardTitle>Your profile</CardTitle>
        <CardDescription>Signed in as @{user.username}</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="username">Username</Label>
            <Input id="username" value={user.username} readOnly disabled />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="display-name">Display name</Label>
            <Input id="display-name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="bio">Bio</Label>
            <Textarea id="bio" rows={3} value={bio} onChange={(e) => setBio(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="avatar-url">Avatar URL</Label>
            <div className="flex items-center gap-3">
              <UserAvatar name={displayName || user.username} url={avatarUrl.trim() || null} size="lg" />
              <Input id="avatar-url" type="url" placeholder="https://..." value={avatarUrl} onChange={(e) => setAvatarUrl(e.target.value)} />
            </div>
          </div>
          {update.isError && (
            <p role="alert" className="text-sm text-destructive">
              {update.error.message}
            </p>
          )}
          <Button type="submit" disabled={update.isPending} className="self-start">
            {update.isPending ? "Saving..." : "Save"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

export default function ProfilePage() {
  const { data: user, isPending } = useMe();
  if (isPending) return <p className="text-sm text-muted-foreground">Loading...</p>;
  // null = logged out; the form needs a user, so ask them to log in.
  if (!user) return <p className="text-sm text-muted-foreground">Please log in to see your profile.</p>;
  // Keyed on id so a different user never inherits the previous form state.
  return <ProfileForm key={user.id} user={user} />;
}
