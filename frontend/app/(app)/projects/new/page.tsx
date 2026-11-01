"use client";
import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowRight, Bot, HelpCircle, Send, Sparkles, Target, User } from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import type { Project } from "@/lib/types";
import { humanize } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { PageSkeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import { PageHeader, ProjectSteps } from "@/components/layout/common";
import { DataSpecChecklist } from "@/components/project/DataSpecChecklist";

const EXAMPLES = [
  "Predict which customers will cancel their subscription next month and why.",
  "Find which products drive the most returns and whether it differs by region.",
  "Forecast daily sales for the next 8 weeks for each store.",
];

function RequirementForm({ onCreated }: { onCreated: (p: Project) => void }) {
  const toast = useToast();
  const [requirement, setRequirement] = React.useState("");
  const [name, setName] = React.useState("");
  const [domain, setDomain] = React.useState("");
  const [goal, setGoal] = React.useState("");
  const [horizon, setHorizon] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (requirement.trim().length < 3) {
      setError("Describe what you want to learn (at least a sentence).");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const context: Record<string, string> = {};
      if (domain.trim()) context.domain = domain.trim();
      if (goal.trim()) context.goal = goal.trim();
      if (horizon.trim()) context.time_horizon = horizon.trim();
      const p = await api.createProject({ requirement: requirement.trim(), name: name.trim() || undefined, context });
      toast.success("Project created");
      onCreated(p);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="grid gap-6 lg:grid-cols-[1fr_20rem]">
      <Card>
        <CardHeader>
          <CardTitle>What do you want to learn?</CardTitle>
          <CardDescription>Describe your goal in plain language. Datrix will ask follow-up questions if needed.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="space-y-2">
            <Label htmlFor="requirement">Requirement</Label>
            <Textarea
              id="requirement"
              required
              rows={6}
              value={requirement}
              onChange={(e) => setRequirement(e.target.value)}
              placeholder="e.g. Predict which customers will churn next month and which factors matter most."
              aria-describedby="requirement-examples"
            />
            <div id="requirement-examples" className="flex flex-wrap gap-2 pt-1">
              {EXAMPLES.map((ex) => (
                <button
                  key={ex}
                  type="button"
                  onClick={() => setRequirement(ex)}
                  className="rounded-full border px-3 py-1 text-left text-xs text-muted-foreground hover:border-primary/50 hover:text-foreground"
                >
                  {ex}
                </button>
              ))}
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="name">
              Project name <span className="font-normal text-muted-foreground">(optional)</span>
            </Label>
            <Input id="name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Generated from the requirement if empty" />
          </div>
          {error && <Alert variant="destructive">{error}</Alert>}
          <div className="flex items-center gap-3">
            <Button type="submit" loading={busy}>
              {busy ? "Analysing requirement…" : "Continue"} {!busy && <ArrowRight />}
            </Button>
            {busy && <span className="text-sm text-muted-foreground">This can take a few seconds.</span>}
          </div>
        </CardContent>
      </Card>
      <Card className="h-fit">
        <CardHeader>
          <CardTitle className="text-sm">Optional context</CardTitle>
          <CardDescription>Helps the analyst ask fewer questions.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="domain">Domain</Label>
            <Input id="domain" value={domain} onChange={(e) => setDomain(e.target.value)} placeholder="e.g. SaaS, retail, healthcare" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="goal">Business goal</Label>
            <Input id="goal" value={goal} onChange={(e) => setGoal(e.target.value)} placeholder="e.g. reduce churn by 10%" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="horizon">Time horizon</Label>
            <Input id="horizon" value={horizon} onChange={(e) => setHorizon(e.target.value)} placeholder="e.g. next month, Q3" />
          </div>
        </CardContent>
      </Card>
    </form>
  );
}

function Bubble({ role, children }: { role: string; children: React.ReactNode }) {
  const isUser = role === "user";
  return (
    <div className={cn("flex gap-2.5", isUser && "flex-row-reverse")}>
      <div
        className={cn(
          "flex size-7 shrink-0 items-center justify-center rounded-full",
          isUser ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground",
        )}
        aria-hidden
      >
        {isUser ? <User className="size-3.5" /> : <Bot className="size-3.5" />}
      </div>
      <div
        className={cn(
          "max-w-[85%] rounded-2xl px-3.5 py-2 text-sm whitespace-pre-wrap",
          isUser ? "rounded-tr-sm bg-primary text-primary-foreground" : "rounded-tl-sm bg-muted",
        )}
      >
        <span className="sr-only">{isUser ? "You: " : "Analyst: "}</span>
        {children}
      </div>
    </div>
  );
}

function Clarify({ project, onUpdate }: { project: Project; onUpdate: (p: Project) => void }) {
  const toast = useToast();
  const [answer, setAnswer] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const endRef = React.useRef<HTMLDivElement>(null);
  const analysis = project.analysis;
  const ready = !!analysis?.ready;

  React.useEffect(() => {
    endRef.current?.scrollIntoView({ block: "nearest" });
  }, [project.messages.length]);

  const send = async (e: React.FormEvent) => {
    e.preventDefault();
    const text = answer.trim();
    if (!text) return;
    setBusy(true);
    try {
      const p = await api.postMessage(project.id, text);
      setAnswer("");
      onUpdate(p);
      if (p.analysis?.ready) toast.success("Requirement is clear", "Here is the data you need.");
    } catch (err) {
      toast.error("Could not send answer", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const hasRequirementMsg = project.messages.some((m) => m.role === "user" && m.content === project.requirement_text);

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_24rem]">
      <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <HelpCircle className="size-4 text-primary" aria-hidden /> Clarifying your goal
            </CardTitle>
            <CardDescription>
              {ready ? "All questions answered." : "Answer the questions below. You can answer several at once."}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="max-h-[28rem] space-y-3 overflow-y-auto pr-1" aria-live="polite">
              {!hasRequirementMsg && <Bubble role="user">{project.requirement_text}</Bubble>}
              {project.messages.map((m) => (
                <Bubble key={m.id} role={m.role}>
                  {m.content}
                </Bubble>
              ))}
              {!ready && analysis?.clarifying_questions?.length ? (
                <Bubble role="assistant">
                  <ol className="list-decimal space-y-1 pl-4">
                    {analysis.clarifying_questions.map((q, i) => (
                      <li key={i}>{q}</li>
                    ))}
                  </ol>
                </Bubble>
              ) : null}
              {busy && (
                <div className="flex items-center gap-2 pl-10 text-sm text-muted-foreground">
                  <span className="size-2 animate-pulse rounded-full bg-current" /> Thinking…
                </div>
              )}
              <div ref={endRef} />
            </div>
            {!ready && (
              <form onSubmit={send} className="mt-4 flex items-end gap-2">
                <div className="flex-1">
                  <Label htmlFor="answer" className="sr-only">
                    Your answer
                  </Label>
                  <Textarea
                    id="answer"
                    rows={2}
                    value={answer}
                    onChange={(e) => setAnswer(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        (e.currentTarget.form as HTMLFormElement | null)?.requestSubmit();
                      }
                    }}
                    placeholder="Type your answer… (Enter to send, Shift+Enter for a new line)"
                    disabled={busy}
                  />
                </div>
                <Button type="submit" size="icon" loading={busy} disabled={!answer.trim()} aria-label="Send answer">
                  {!busy && <Send />}
                </Button>
              </form>
            )}
          </CardContent>
        </Card>
        {ready && analysis && <DataSpecChecklist projectId={project.id} spec={analysis.data_spec} />}
      </div>

      <div className="space-y-4">
        {analysis && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-sm">
                <Sparkles className="size-4 text-primary" aria-hidden /> Understanding so far
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <Badge>{humanize(analysis.task_type)}</Badge>
                <Badge variant={ready ? "success" : "warning"}>{ready ? "Ready" : "Needs answers"}</Badge>
              </div>
              <p>{analysis.summary}</p>
              {analysis.success_criteria?.length > 0 && (
                <div>
                  <h4 className="mb-1 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    <Target className="size-3.5" aria-hidden /> You will get
                  </h4>
                  <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
                    {analysis.success_criteria.map((c, i) => (
                      <li key={i}>{c}</li>
                    ))}
                  </ul>
                </div>
              )}
            </CardContent>
          </Card>
        )}
        {ready && (
          <Link href={`/projects/${project.id}/data`} className={cn(buttonVariants({ size: "lg" }), "w-full")}>
            Continue to data upload <ArrowRight />
          </Link>
        )}
      </div>
    </div>
  );
}

function WizardInner() {
  const router = useRouter();
  const params = useSearchParams();
  const pid = Number(params.get("project")) || null;
  const [project, setProject] = React.useState<Project | null>(null);
  const [loading, setLoading] = React.useState(!!pid);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!pid) {
      setProject(null);
      setLoading(false);
      return;
    }
    if (project?.id === pid) return;
    setLoading(true);
    api
      .getProject(pid)
      .then((p) => {
        setProject(p);
        setError(null);
      })
      .catch((e) => setError(errorMessage(e)))
      .finally(() => setLoading(false));
  }, [pid, project?.id]);

  const onCreated = (p: Project) => {
    setProject(p);
    router.replace(`/projects/new?project=${p.id}`);
  };

  return (
    <>
      {project && <ProjectSteps projectId={project.id} status={project.status} current="requirement" />}
      <PageHeader
        eyebrow={project ? "Project" : "New project"}
        title={project ? project.name : "Describe your analysis"}
        description={project ? undefined : "Tell Datrix what you want to find out. It works out the data it needs from you."}
      />
      {error && (
        <Alert variant="destructive" title="Could not load project" className="mb-4">
          {error}
        </Alert>
      )}
      {loading ? <PageSkeleton /> : project ? <Clarify project={project} onUpdate={setProject} /> : !error && <RequirementForm onCreated={onCreated} />}
    </>
  );
}

export default function NewProjectPage() {
  return (
    <React.Suspense fallback={<PageSkeleton />}>
      <WizardInner />
    </React.Suspense>
  );
}
