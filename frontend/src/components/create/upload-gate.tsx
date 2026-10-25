"use client";

import { UploadFlow } from "@/components/create/upload-flow";
import { HostedNote } from "@/components/hosted-note";
import { PageHeader } from "@/components/motion/page-header";
import { useHosted } from "@/lib/queries";

/** /create/upload, or a one-line note where it would be on a hosted demo (no code may be uploaded there). */
export function UploadGate() {
  if (useHosted()) {
    return (
      <div className="grid min-w-0 gap-4">
        <PageHeader title="Upload" eyebrow="HFT · Create" />
        <HostedNote />
      </div>
    );
  }
  return <UploadFlow />;
}
