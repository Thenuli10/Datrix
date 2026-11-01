"use client";
import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, CheckCheck, Upload } from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import { useIdParam, useLoad, useSingleFlight } from "@/lib/hooks";
import type { ColumnMapping, Dataset, Validation } from "@/lib/types";
import { Alert } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageSkeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { PageHeader, ProjectSteps } from "@/components/layout/common";
import { DataSpecChecklist } from "@/components/project/DataSpecChecklist";
import { FileDropzone } from "@/components/project/FileDropzone";
import { GapReport, JoinsList } from "@/components/project/GapReport";
import { MappingEditor } from "@/components/project/MappingEditor";
import { ProfilePreview } from "@/components/project/ProfilePreview";
import { cn } from "@/lib/utils";

export default function DataPage() {
  const id = useIdParam();
  const router = useRouter();
  const toast = useToast();

  const project = useLoad(() => api.getProject(id), [id]);
  const spec = useLoad(() => api.getDataSpec(id), [id]);
  const datasets = useLoad(() => api.listDatasets(id), [id]);
  const validation = useLoad(() => api.getValidation(id), [id]);

  const [files, setFiles] = React.useState<File[]>([]);
  const [progress, setProgress] = React.useState<number | null>(null);
  const [validating, setValidating] = React.useState(false);
  const once = useSingleFlight();
  const [savingMap, setSavingMap] = React.useState(false);
  const [deleting, setDeleting] = React.useState<number | null>(null);

  const initial: Dataset[] = React.useMemo(
    () => (datasets.data ?? []).filter((d) => d.purpose !== "rerun"),
    [datasets.data],
  );
  const v: Validation | null | undefined = validation.data;
  const mapping: ColumnMapping[] = React.useMemo(
    () => (v ? (v.column_mapping_json?.length ? v.column_mapping_json : (v.gap_report_json?.mapping ?? [])) : []),
    [v],
  );
  const stale =
    !!v && (initial.length !== v.dataset_ids.length || initial.some((d) => !v.dataset_ids.includes(d.id)));

  const upload = async () => {
    if (!files.length) return;
    setProgress(0);
    try {
      const added = await api.uploadDatasets(id, files, setProgress);
      datasets.setData((ds) => [...(ds ?? []), ...added]);
      setFiles([]);
      toast.success(`Uploaded ${added.length} file${added.length === 1 ? "" : "s"}`, "Now run the validator.");
      void project.reload();
    } catch (e) {
      toast.error("Upload failed", errorMessage(e));
    } finally {
      setProgress(null);
    }
  };

  const runValidate = () =>
    once(async () => {
      setValidating(true);
      try {
        const res = await api.validate(id);
        validation.setData(res);
        void project.reload();
        toast.success(
          res.status === "needs_more_data" ? "Validation found gaps" : "Data validated",
          res.status === "needs_more_data" ? "See the gap report below." : undefined,
        );
      } catch (e) {
        toast.error("Validation failed", errorMessage(e));
      } finally {
        setValidating(false);
      }
    });

  const saveMapping = async (m: ColumnMapping[]) => {
    setSavingMap(true);
    try {
      const res = await api.putColumnMapping(id, m);
      validation.setData(res);
      void project.reload();
      toast.success("Mapping saved");
    } catch (e) {
      toast.error("Could not save mapping", errorMessage(e));
    } finally {
      setSavingMap(false);
    }
  };

  const remove = async (d: Dataset) => {
    if (!window.confirm(`Remove ${d.original_name} from this project?`)) return;
    setDeleting(d.id);
    try {
      await api.deleteDataset(id, d.id);
      datasets.setData((ds) => (ds ?? []).filter((x) => x.id !== d.id));
      toast.info(`Removed ${d.original_name}`);
    } catch (e) {
      toast.error("Could not remove file", errorMessage(e));
    } finally {
      setDeleting(null);
    }
  };

  if (project.loading && !project.data) return <PageSkeleton />;
  if (project.error || !project.data) {
    return <Alert variant="destructive" title="Could not load project">{project.error}</Alert>;
  }
  const p = project.data;
  const canPlan = !!v && v.status !== "needs_more_data" && !stale;
  const uploading = progress !== null;

  return (
    <>
      <ProjectSteps projectId={id} status={p.status} current="data" />
      <PageHeader
        eyebrow="Step 2 · Data"
        title={p.name}
        description="Upload one or more files. The validator maps your columns to the spec, checks joins between files, and reports anything missing."
        actions={
          canPlan && (
            <Button onClick={() => router.push(`/projects/${id}/plan`)}>
              Continue to plan <ArrowRight />
            </Button>
          )
        }
      />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_24rem]">
        <div className="min-w-0 space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Upload data</CardTitle>
              <CardDescription>Add every file you have. Datrix will work out how they join.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <FileDropzone files={files} onChange={setFiles} disabled={uploading} />
              {uploading && (
                <div className="space-y-1" aria-live="polite">
                  <div className="h-2 overflow-hidden rounded-full bg-muted">
                    <div className="h-full bg-primary transition-all" style={{ width: `${Math.round((progress ?? 0) * 100)}%` }} />
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {progress! < 1 ? `Uploading… ${Math.round(progress! * 100)}%` : "Profiling files…"}
                  </p>
                </div>
              )}
              <div className="flex flex-wrap gap-2">
                <Button onClick={() => void upload()} disabled={!files.length} loading={uploading}>
                  <Upload /> Upload {files.length > 0 ? `${files.length} file${files.length === 1 ? "" : "s"}` : ""}
                </Button>
                <Button
                  variant={v && !stale ? "outline" : "default"}
                  onClick={() => void runValidate()}
                  disabled={!initial.length || uploading}
                  loading={validating}
                >
                  <CheckCheck /> {validating ? "Validating…" : v ? "Re-validate" : "Validate"}
                </Button>
              </div>
              {validating && (
                <p className="text-sm text-muted-foreground" aria-live="polite">
                  The validator is inspecting profiles, samples and joins. This can take up to a minute.
                </p>
              )}
              {stale && (
                <Alert variant="warning" title="Files changed since the last validation">
                  Run the validator again so the mapping and gap report match your current files.
                </Alert>
              )}
            </CardContent>
          </Card>

          {datasets.error && <Alert variant="destructive" title="Could not load files">{datasets.error}</Alert>}
          {initial.length > 0 && <ProfilePreview datasets={initial} onDelete={remove} deleting={deleting} />}

          {v && <GapReport report={v.gap_report_json} />}
          {v && v.gap_report_json?.joins?.length > 0 && <JoinsList joins={v.gap_report_json.joins} datasets={initial} />}
          {v && spec.data && (
            <MappingEditor spec={spec.data} mapping={mapping} datasets={initial} onSave={saveMapping} saving={savingMap} />
          )}

          {canPlan && (
            <div className="flex justify-end">
              <Link href={`/projects/${id}/plan`} className={cn(buttonVariants({ size: "lg" }))}>
                Continue to plan <ArrowRight />
              </Link>
            </div>
          )}
        </div>

        <div className="min-w-0 space-y-4 lg:sticky lg:top-20 lg:self-start">
          {spec.loading && !spec.data ? (
            <Card className="h-64 animate-pulse" />
          ) : spec.data ? (
            <DataSpecChecklist projectId={id} spec={spec.data} mapping={v ? mapping : undefined} compact />
          ) : (
            <Alert variant="warning" title="No data spec yet">
              {spec.error ?? "Finish the requirement step first."}{" "}
              <Link className="underline" href={`/projects/new?project=${id}`}>
                Go to requirement
              </Link>
            </Alert>
          )}
        </div>
      </div>
    </>
  );
}
