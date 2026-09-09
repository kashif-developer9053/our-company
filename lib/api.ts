// Frontend API client for the Phase 2 backend. All mock-data reads are replaced
// by these calls. Base URL comes from NEXT_PUBLIC_API_BASE (defaults to the
// local backend).

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") || "http://localhost:8000";

// Human-readable label per internal role_key.
export const ROLE_LABELS: Record<string, string> = {
  supervisor: "Manager",
  researcher: "Researcher",
  verifier: "Verifier",
  outreach: "Outreach",
  it_monitor: "System Health",
  custom: "Custom",
};
export const roleLabel = (key: string) => ROLE_LABELS[key] || "Custom";

// Lead status → badge label + color (covers all backend statuses).
export const LEAD_STATUS_META: Record<string, { label: string; color: string }> = {
  new: { label: "New", color: "#8a93a6" },
  verified: { label: "Verified", color: "#26c6da" },
  rejected: { label: "Rejected", color: "#ef5350" },
  mailed: { label: "Mailed", color: "#8a93a6" },
  replied: { label: "Replied", color: "#4aa3ff" },
  not_interested: { label: "Not Interested", color: "#ef5350" },
  interested_awaiting_review: { label: "Interested — Awaiting You", color: "#f2c14e" },
};
export const leadStatusMeta = (s: string) =>
  LEAD_STATUS_META[s] || { label: s, color: "#8a93a6" };

// The status values the CRM UI offers when editing a lead.
export const LEAD_STATUS_OPTIONS = Object.keys(LEAD_STATUS_META);

// ---- auth token storage ---------------------------------------------------
const TOKEN_KEY = "aiagency_token";
export const getToken = () =>
  typeof window === "undefined" ? null : localStorage.getItem(TOKEN_KEY);
export const setToken = (t: string) => localStorage.setItem(TOKEN_KEY, t);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });
  // A 401 on the login/setup endpoints is a bad-credentials response, not an
  // expired session — surface the real message and don't trigger a logout.
  const isAuthAttempt = path.startsWith("/auth/login") || path.startsWith("/auth/setup");
  if (res.status === 401 && !isAuthAttempt) {
    // Session missing/expired — drop it and tell the app to show login.
    clearToken();
    if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent("auth:unauthorized"));
    throw new Error("Not authenticated");
  }
  if (!res.ok) {
    let msg = `${res.status}`;
    try {
      const body = await res.json();
      msg = body.detail || body.error || msg;
    } catch {
      /* ignore */
    }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

// ---- types ----------------------------------------------------------------
export interface LiveAgent {
  id: string;
  name: string;
  role_key: string;
  responsibility: string;
  status: string;
  location: string;
  is_default: boolean;
  task?: string; // live task description shown while working
  ai_config?: { provider_id: string; model: string; fallback_provider_id: string | null; fallback_model: string | null };
  created_at?: string;
}

export interface LiveStatus {
  office_open: boolean;
  meeting_in_progress: boolean;
  agents: Record<string, LiveAgent>;
  backend: string;
}

export interface ApiLead {
  id: string;
  business_name: string;
  niche: string;
  country: string;
  city: string;
  phone: string;
  email: string;
  website: string;
  status: string;
  last_action: string;
  last_action_timestamp: string;
  notes: string;
  created_at?: string;
  has_working_website?: boolean | null;
  email_confidence?: string;
  rejection_reason?: string;
  source?: string;
  discovery_source?: string;
  // Why this lead was collected, backed by a real website audit.
  collection_reason?: string;
  opportunity_score?: number;
  pitch_points?: string[];
  site_audit?: {
    url?: string; score?: number; qualified?: boolean; headline?: string; summary?: string;
    findings?: { code: string; severity: string; title: string; evidence: string; pitch: string }[];
  };
  outreach_history?: { type: string; subject?: string; body?: string; sent_at?: string; received_at?: string }[];
  reply_classification?: string;
  reply_reasoning?: string;
  suggested_reply?: string;
  call_scheduled?: string;
}

export interface PipelineRun {
  id: string;
  niche_name: string;
  industry: string;
  country: string;
  city: string;
  status: string; // running | complete | error
  found: number;
  verified: number;
  rejected: number;
  reasons: Record<string, number>;
  message: string;
  created_at: string;
  finished_at: string;
}

export interface LeadStats {
  leadsFound: number;
  leadsVerified: number;
  emailsSent: number;
  repliesReceived: number;
  interested: number;
  notInterested: number;
  pendingResponse: number;
}

export interface SettingKey {
  key_name: string;
  label: string;
  group: string; // claude | smtp | imap
  secret: boolean;
  testable: boolean;
  is_set: boolean;
  value: string; // full value for non-secret keys (emails); empty for secrets
  masked: string;
  updated_at: string;
}

// ---- status board ---------------------------------------------------------
export const getStatus = () => req<{ status: LiveStatus }>("/status").then((r) => r.status);
export const setOffice = (open: boolean) =>
  req<{ status: LiveStatus }>("/status/office", { method: "POST", body: JSON.stringify({ open }) }).then((r) => r.status);
export const setMeeting = (in_progress: boolean) =>
  req<{ status: LiveStatus }>("/status/meeting", { method: "POST", body: JSON.stringify({ in_progress }) }).then((r) => r.status);

// ---- agents ---------------------------------------------------------------
export const getAgents = () => req<{ agents: LiveAgent[] }>("/agents").then((r) => r.agents);
export const createAgent = (body: { name: string; responsibility: string; role_key: string }) =>
  req<{ agent: LiveAgent }>("/agents", { method: "POST", body: JSON.stringify(body) }).then((r) => r.agent);
export const updateAgent = (id: string, body: Partial<{ name: string; responsibility: string; role_key: string; status: string }>) =>
  req<{ agent: LiveAgent }>(`/agents/${id}`, { method: "PUT", body: JSON.stringify(body) }).then((r) => r.agent);
export const deleteAgent = (id: string) =>
  req<{ deleted: string }>(`/agents/${id}`, { method: "DELETE" });

// ---- leads ----------------------------------------------------------------
export const getLeads = (params?: { status?: string; q?: string }) => {
  const qs = new URLSearchParams();
  if (params?.status) qs.set("status", params.status);
  if (params?.q) qs.set("q", params.q);
  const suffix = qs.toString() ? `?${qs}` : "";
  return req<{ leads: ApiLead[] }>(`/leads${suffix}`).then((r) => r.leads);
};
export const getLeadStats = () => req<{ stats: LeadStats; total: number }>("/leads/stats");
export const createLead = (body: Partial<ApiLead> & { business_name: string }) =>
  req<{ lead: ApiLead }>("/leads", { method: "POST", body: JSON.stringify(body) }).then((r) => r.lead);
export const updateLead = (id: string, body: Partial<ApiLead>) =>
  req<{ lead: ApiLead }>(`/leads/${id}`, { method: "PUT", body: JSON.stringify(body) }).then((r) => r.lead);
export const deleteLead = (id: string) =>
  req<{ deleted: string }>(`/leads/${id}`, { method: "DELETE" });

// ---- settings -------------------------------------------------------------
export const getSettings = () =>
  req<{ keys: SettingKey[]; config: { daily_send_cap: number }; encryption_secret_set: boolean }>("/settings");
export const saveSetting = (key_name: string, value: string) =>
  req<{ ok: boolean }>("/settings", { method: "POST", body: JSON.stringify({ key_name, value }) });
export const deleteSetting = (key_name: string) =>
  req<{ deleted: string }>(`/settings/${key_name}`, { method: "DELETE" });
export const saveConfig = (daily_send_cap: number) =>
  req<{ config: { daily_send_cap: number } }>("/settings/config", { method: "POST", body: JSON.stringify({ daily_send_cap }) });
export const testClaude = () => req<{ ok: boolean; message: string }>("/settings/test/claude", { method: "POST" });
export const testSmtp = () => req<{ ok: boolean; message: string }>("/settings/test/smtp", { method: "POST" });
export const testImap = () => req<{ ok: boolean; message: string }>("/settings/test/imap", { method: "POST" });
export const imapSameAsSmtp = () => req<{ ok: boolean }>("/settings/imap-same-as-smtp", { method: "POST" });

// ---- Agent 3 outreach + replies -------------------------------------------
export const sendOutreach = (lead_ids?: string[]) =>
  req<{ ok: boolean; note?: string; error?: string }>("/agent3/send-outreach", { method: "POST", body: JSON.stringify({ lead_ids: lead_ids ?? null }) });
export const checkReplies = () =>
  req<{ ok: boolean; processed?: number; error?: string }>("/agent3/check-replies", { method: "POST" });

export interface PendingReply {
  id: string;
  business_name: string;
  niche: string;
  email: string;
  reply: string;
  classification: string;
  reasoning: string;
  suggested_reply: string;
}
export const getPendingReplies = () => req<{ pending: PendingReply[] }>("/agent3/replies/pending").then((r) => r.pending);
export const sendLeadReply = (leadId: string, mode: "as_is" | "edit" | "manual", body?: string) =>
  req<{ ok: boolean; error?: string }>(`/agent3/leads/${leadId}/reply`, { method: "POST", body: JSON.stringify({ mode, body }) });
export const scheduleCall = (leadId: string, call_scheduled: string) =>
  req<{ ok: boolean }>(`/agent3/leads/${leadId}/schedule-call`, { method: "POST", body: JSON.stringify({ call_scheduled }) });

// ---- auth ------------------------------------------------------------------
export interface User {
  id: string;
  name: string;
  email: string;
  role: string;
  is_active: boolean;
  created_at?: string;
  last_login?: string;
}

export const needsSetup = () => req<{ needs_setup: boolean }>("/auth/needs-setup");
export const setupAdmin = (name: string, email: string, password: string) =>
  req<{ token: string; user: User }>("/auth/setup", { method: "POST", body: JSON.stringify({ name, email, password }) });
export const login = (email: string, password: string) =>
  req<{ token: string; user: User }>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
export const logout = () => req<{ ok: boolean }>("/auth/logout", { method: "POST" });
export const getMe = () => req<{ user: User }>("/auth/me").then((r) => r.user);

// ---- users (admin) + self --------------------------------------------------
export const getUsers = () => req<{ users: User[] }>("/users").then((r) => r.users);
export const createUser = (body: { name: string; email: string; role: string; password?: string }) =>
  req<{ user: User; temporary_password: string | null }>("/users", { method: "POST", body: JSON.stringify(body) });
export const updateUser = (id: string, body: Partial<{ name: string; email: string; role: string; is_active: boolean }>) =>
  req<{ user: User }>(`/users/${id}`, { method: "PUT", body: JSON.stringify(body) });
export const deleteUser = (id: string) => req<{ deleted: string }>(`/users/${id}`, { method: "DELETE" });
export const resetUserPassword = (id: string, new_password: string) =>
  req<{ ok: boolean }>(`/users/${id}/password`, { method: "PUT", body: JSON.stringify({ new_password }) });
export const changeMyPassword = (current_password: string, new_password: string) =>
  req<{ ok: boolean }>("/users/me/password", { method: "PUT", body: JSON.stringify({ current_password, new_password }) });
export const updateMyProfile = (body: { name?: string; email?: string }) =>
  req<{ user: User }>("/users/me", { method: "PUT", body: JSON.stringify(body) }).then((r) => r.user);

// ---- reasoning: niches + chat ---------------------------------------------
export interface NicheItem { niche_name: string; reasoning: string; selected?: boolean }
export interface NicheRecord {
  id: string;
  industry: string;
  country: string;
  city: string;
  selection_reasoning?: string | null; // set only when Agent 1 self-picked industry/country
  niches: NicheItem[];
  status: string;
  supervisor_note: string;
  approved_niche: string;
  created_at?: string;
}

export const findNiches = (body: { industry?: string; country?: string; city?: string }) =>
  req<{ ok: boolean; record?: NicheRecord; error?: string; error_kind?: string }>("/agent1/find-niches", { method: "POST", body: JSON.stringify(body) });
export const getPendingNiches = () => req<{ pending: NicheRecord[] }>("/agent1/niches/pending").then((r) => r.pending);
export const approveNiche = (id: string, niche_name: string) =>
  req<{ ok: boolean; approved_niche: string; note: string }>(`/agent1/niches/${id}/approve`, { method: "POST", body: JSON.stringify({ niche_name }) });
export const rejectNiches = (id: string) =>
  req<{ ok: boolean; note: string }>(`/agent1/niches/${id}/reject-all`, { method: "POST", body: JSON.stringify({}) });
// ---- notifications (CEO inbox) --------------------------------------------
export interface AppNotification {
  id: string; kind: "approval" | "config" | "alert" | "info";
  title: string; body: string; agent_id: string; action: string;
  ref_id: string; read: boolean; resolved: boolean; created_at: string;
}
export const getNotifications = () =>
  req<{ ok: boolean; notifications: AppNotification[]; unread: number }>("/notifications");
export const getNotificationCount = () => req<{ ok: boolean; unread: number }>("/notifications/count");
export const markNotificationRead = (id: string) =>
  req<{ ok: boolean }>(`/notifications/${id}/read`, { method: "POST" });
export const markAllNotificationsRead = () =>
  req<{ ok: boolean; updated: number }>("/notifications/read-all", { method: "POST" });

// ---- pending lead batches (CEO approval gate) ------------------------------
export interface PendingBatch {
  batch_id: string; niche: string; city: string; country: string;
  created_at: string; leads: ApiLead[];
}
export const getPendingLeads = () =>
  req<{ ok: boolean; batches: PendingBatch[]; total: number }>("/pipeline/pending-leads");
export const approveLeadBatch = (batchId: string, lead_ids?: string[]) =>
  req<{ ok: boolean; approved: number; outreach: { started: boolean; reason?: string; count?: number; queued?: number } }>(
    `/pipeline/pending-leads/${batchId}/approve`, { method: "POST", body: JSON.stringify(lead_ids ? { lead_ids } : {}) });
export const rejectLeadBatch = (batchId: string) =>
  req<{ ok: boolean; rejected: number }>(`/pipeline/pending-leads/${batchId}/reject`, { method: "POST" });

// ---- Agent 3 email drafts (CEO reviews before anything is sent) -----------
export interface EmailDraft {
  id: string; batch_id: string; lead_id: string; business_name: string; to_email: string;
  subject: string; body: string; html: string; preview_html?: string; spam_flags: string[];
  collection_reason: string; opportunity_score: number;
  status: "pending" | "approved" | "rejected" | "sent" | "failed";
  edited: boolean; created_at: string; sent_at?: string; error?: string;
}
export interface DraftTarget { value: string; count: number }
export const getDraftTargets = () =>
  req<{ ok: boolean; total: number; cities: DraftTarget[]; niches: DraftTarget[] }>("/agent3/draft-targets");
export const draftEmailBatch = (body: { count?: number; lead_ids?: string[]; city?: string; niche?: string }) =>
  req<{ ok: boolean; batch_id?: string; drafted?: number; note?: string;
        failed?: { lead: string; error: string }[] }>("/agent3/draft-batch", { method: "POST", body: JSON.stringify(body) });
export const getDrafts = (status = "pending") =>
  req<{ ok: boolean; drafts: EmailDraft[]; total: number }>(`/agent3/drafts?status=${status}`);
export const editDraft = (id: string, body: { subject?: string; body?: string; to_email?: string }) =>
  req<{ ok: boolean; draft: EmailDraft }>(`/agent3/drafts/${id}`, { method: "PUT", body: JSON.stringify(body) });
export const rejectDrafts = (body: { draft_ids?: string[]; batch_id?: string }) =>
  req<{ ok: boolean; rejected: number }>("/agent3/drafts/reject", { method: "POST", body: JSON.stringify(body) });
export const approveAndSendDrafts = (body: { draft_ids?: string[]; batch_id?: string }) =>
  req<{ ok: boolean; approved?: number; sent?: number; note?: string; error?: string }>(
    "/agent3/drafts/approve-send", { method: "POST", body: JSON.stringify(body) });

// ---- follow-up sequencing --------------------------------------------------
// Most cold-outreach replies arrive on the 2nd-4th touch, so this is where the
// unreplied leads queue up. Drafting is automatic; sending still needs approval.
export interface FollowupItem {
  lead_id: string; business_name: string; email: string; city: string; niche: string;
  angle: "gentle_bump" | "new_angle" | "breakup"; emails_sent: number;
  last_sent_at: string; fit_score: number;
}
export const getFollowupsDue = (limit = 100) =>
  req<{ ok: boolean; total: number; items: FollowupItem[] }>(`/agent3/followups/due?limit=${limit}`);
export const draftFollowups = (body: { count?: number; dry_run?: boolean }) =>
  req<{ ok: boolean; batch_id?: string; queued?: number; drafted?: number; message?: string }>(
    "/agent3/followups/draft", { method: "POST", body: JSON.stringify(body) });

// ---- deliverability (bounce tracking + suppression) ------------------------
// Bounce rate is what decides whether the sending domain survives. Providers
// start filtering a domain sustaining more than ~3-5% hard bounces.
export interface Deliverability {
  days: number; events: Record<string, number>; delivered: number;
  hard_bounces: number; soft_bounces: number; bounce_rate_pct: number;
  suppressed_total: number; safe_to_scale: boolean;
}
export const getDeliverability = (days = 30) =>
  req<{ ok: boolean } & Deliverability>(`/agent3/deliverability?days=${days}`);
export const getWebhookUrl = () =>
  req<{ ok: boolean; path: string }>("/agent3/webhook-url");
export const verifyEmails = (body: { limit?: number; only_guessed?: boolean }) =>
  req<{ ok: boolean; checked: number; results?: Record<string, number>; message?: string }>(
    "/agent3/verify-emails", { method: "POST", body: JSON.stringify(body) });

// ---- mailbox (Gmail-style folder view of outreach) ------------------------
export interface MailItem {
  id: string; kind: "outbound" | "inbound"; business_name: string; to_email: string;
  subject: string; preview: string; body: string; html: string; at: string;
  status: string; error?: string; edited?: boolean; spam_flags?: string[];
  collection_reason?: string; lead_id?: string; reply_reasoning?: string; suggested_reply?: string;
  read?: boolean; archived?: boolean;
}
export interface MailCounts {
  drafts: number; sent: number; failed: number; rejected: number;
  inbox: number; archive: number; unread: number;
}
// Inbox actions. A reply is addressed by lead id + when it arrived.
type ReplyRef = { lead_id: string; received_at: string };
export const markReplyRead = (b: ReplyRef) =>
  req<{ ok: boolean }>("/agent3/inbox/read", { method: "POST", body: JSON.stringify(b) });
export const archiveReply = (b: ReplyRef) =>
  req<{ ok: boolean }>("/agent3/inbox/archive", { method: "POST", body: JSON.stringify(b) });
export const unarchiveReply = (b: ReplyRef) =>
  req<{ ok: boolean }>("/agent3/inbox/unarchive", { method: "POST", body: JSON.stringify(b) });
export const deleteReply = (b: ReplyRef) =>
  req<{ ok: boolean }>("/agent3/inbox/delete", { method: "POST", body: JSON.stringify(b) });
export const sendInboxReply = (b: ReplyRef & { subject?: string; body: string }) =>
  req<{ ok: boolean; note?: string; error?: string }>("/agent3/inbox/send-reply", { method: "POST", body: JSON.stringify(b) });
export const getMailbox = (folder: string) =>
  req<{ ok: boolean; folder: string; items: MailItem[]; counts: MailCounts }>(`/agent3/mailbox?folder=${folder}`);

export const retryFailedDrafts = (body: { draft_ids?: string[] }) =>
  req<{ ok: boolean; retried?: number; note?: string; error?: string }>("/agent3/drafts/retry", { method: "POST", body: JSON.stringify(body) });

// ---- WhatsApp outreach (click-to-send, manual) ----------------------------
export interface WhatsAppLead {
  id: string; business_name: string; niche: string; city: string;
  phone_raw: string; number: string; usable: boolean;
  status: "not_contacted" | "message_sent" | "replied" | "interested" | "not_interested" | "invalid_number";
  remarks: string; message: string; sent_at: string; updated_at: string;
  collection_reason: string; opportunity_score: number;
  site_audit?: { findings?: { code: string; severity: string; title: string; evidence: string; pitch: string }[] };
}
export const getWhatsAppLeads = (status = "all") =>
  req<{ ok: boolean; leads: WhatsAppLead[]; counts: Record<string, number> }>(`/agent3/whatsapp/leads?status=${status}`);
export const writeWhatsAppMessage = (lead_id: string, language: "english" | "roman_urdu" = "english") =>
  req<{ ok: boolean; lead_id?: string; number?: string; message?: string; link?: string; error?: string }>(
    "/agent3/whatsapp/message", { method: "POST", body: JSON.stringify({ lead_id, language }) });
export const updateWhatsAppLead = (id: string, body: { status?: string; remarks?: string; message?: string }) =>
  req<{ ok: boolean; lead: WhatsAppLead }>(`/agent3/whatsapp/leads/${id}`, { method: "PUT", body: JSON.stringify(body) });

export interface NextOption { action: string; label: string; hint: string }
export const harvestLeads = (body: { niche: string; city?: string; country?: string; target?: number; exclude_existing?: boolean }) =>
  req<{
    ok: boolean; batch_id?: string; added?: number; found?: number; target?: number;
    complete?: boolean; rounds?: number; examined?: number; elapsed_seconds?: number;
    rejected?: { no_contact: number; good_site: number; guessed_email_only: number };
    message?: string; next_options?: NextOption[]; error?: string;
  }>("/agent1/harvest-leads", { method: "POST", body: JSON.stringify(body) });

export const generateLeads = (body: { niche: string; city?: string; country?: string; count?: number }) =>
  req<{ ok: boolean; added?: number; skipped?: number; no_reason?: number; dropped_no_reason?: number;
       note?: string; niche?: string; error?: string }>("/agent1/generate-leads", { method: "POST", body: JSON.stringify(body) });

export type ChatMsg = { role: "user" | "agent"; content: string };

// Route a chat message to the right endpoint for any agent (default or custom).
function chatPath(agentId: string): string {
  switch (agentId) {
    case "supervisor": return "/supervisor/chat";
    case "agent1": return "/agent1/chat";
    case "agent2": return "/agent2/chat";
    case "agent3": return "/agent3/chat";
    case "it_monitor": return "/it-monitor/chat";
    default: return `/agents/${agentId}/chat`; // custom agents
  }
}
export const agentChat = (agentId: string, message: string, history: ChatMsg[]) =>
  req<{ ok: boolean; reply?: string; error?: string }>(chatPath(agentId), { method: "POST", body: JSON.stringify({ message, history }) });

// ---- daily standup ---------------------------------------------------------
export interface Standup {
  date: string;
  reports: { agent: string; text: string }[];
  summary: string;
}
export const getStandup = () => req<{ standup: Standup }>("/supervisor/standup").then((r) => r.standup);

// ---- Phase 8: build new agents (admin) ------------------------------------
export interface AgentRequest {
  request_id: string;
  agent_name: string;
  description_given: string;
  status: string; // building | awaiting_review | approved | rejected
  files_added: string[];
  files_modified: string[];
  test_results: { check_name: string; passed: boolean; detail: string }[];
  warnings: string[];
  overall_ready: boolean;
  generated_at: string;
  feedback?: string;
  live_agent_id?: string;
  deployed_file?: string;
}
export const requestNewAgent = (agent_name: string, description: string, needs_reasoning: boolean) =>
  req<{ request_id: string; message: string }>("/it-monitor/request-new-agent", { method: "POST", body: JSON.stringify({ agent_name, description, needs_reasoning }) });
export const getAgentRequests = () => req<{ requests: AgentRequest[] }>("/it-monitor/agent-requests").then((r) => r.requests);
export const approveAgentRequest = (id: string) =>
  req<{ message: string; agent: { id: string; name: string } }>(`/it-monitor/agent-requests/${id}/approve`, { method: "POST" });
export const rejectAgentRequest = (id: string, feedback: string) =>
  req<{ message: string }>(`/it-monitor/agent-requests/${id}/reject`, { method: "POST", body: JSON.stringify({ feedback }) });

// ---- Phase 10: AI providers -----------------------------------------------
export interface AiProvider {
  provider_id: string; display_name: string; kind: string; needs_base_url: boolean;
  base_url: string; available_models: string[]; is_set: boolean; last_four: string;
  status: string; last_tested_at: string;
}
export const getProviders = () => req<{ providers: AiProvider[] }>("/settings/providers").then((r) => r.providers);
export const saveProvider = (provider_id: string, api_key?: string, base_url?: string) =>
  req<{ ok: boolean }>("/settings/providers", { method: "POST", body: JSON.stringify({ provider_id, api_key, base_url }) });
export const deleteProvider = (id: string) => req<{ ok: boolean }>(`/settings/providers/${id}`, { method: "DELETE" });
export const testProvider = (id: string) => req<{ ok: boolean; message: string }>(`/settings/providers/${id}/test`, { method: "POST" });
export const fetchProviderModels = (id: string) => req<{ ok: boolean; models: string[]; error: string }>(`/settings/providers/${id}/models`);

// ---- company profile ------------------------------------------------------
export interface CompanyProfile {
  company_name: string; website: string; tagline: string; services_offered: string[];
  tone_preference: string; contact_links: { label: string; url: string }[]; outreach_template: string;
  contact_email?: string; whatsapp?: string; phone?: string; logo_url?: string;
  sender_name?: string; sender_title?: string;
}
export const getCompany = () => req<{ profile: CompanyProfile }>("/settings/company").then((r) => r.profile);
export const saveCompany = (profile: CompanyProfile) =>
  req<{ profile: CompanyProfile }>("/settings/company", { method: "POST", body: JSON.stringify(profile) }).then((r) => r.profile);

// ---- usage & cost ---------------------------------------------------------
export const getUsage = (range: string) =>
  req<{ range: string; total_calls: number; total_cost: number; by_agent: Record<string, { calls: number; input_tokens: number; output_tokens: number; est_cost: number; providers: Record<string, number> }>; by_provider: Record<string, { calls: number; est_cost: number }> }>(`/settings/usage?range=${range}`);

// ---- per-agent AI config + instructions -----------------------------------
export interface AiConfig { provider_id: string; model: string; fallback_provider_id: string | null; fallback_model: string | null }
export const setAgentAiConfig = (id: string, cfg: AiConfig) =>
  req<{ agent: LiveAgent }>(`/agents/${id}/ai-config`, { method: "PUT", body: JSON.stringify(cfg) });
export interface InstrVersion { version: number; instructions: string; created_by: string; created_at: string; is_active: boolean }
export const getInstructions = (id: string) => req<{ active: string; versions: InstrVersion[] }>(`/agents/${id}/instructions`);
export const saveInstructions = (id: string, instructions: string) =>
  req<{ version: number }>(`/agents/${id}/instructions`, { method: "POST", body: JSON.stringify({ instructions }) });
export const activateInstructions = (id: string, version: number) =>
  req<{ active_version: number }>(`/agents/${id}/instructions/activate`, { method: "POST", body: JSON.stringify({ version }) });
export const testDraftInstructions = (id: string, draft_instructions: string, sample_message: string) =>
  req<{ ok: boolean; output: string; error?: string }>(`/agents/${id}/instructions/test`, { method: "POST", body: JSON.stringify({ draft_instructions, sample_message }) });

// ---- knowledge base -------------------------------------------------------
export interface KbEntry { id: string; title: string; content_type: string; scope: string; agent_id: string | null; original_filename: string | null; chars: number; uploaded_at: string }
export const getKb = () => req<{ entries: KbEntry[] }>("/knowledge").then((r) => r.entries);
export const addKbText = (title: string, content: string, scope: string, agent_id: string | null) =>
  req<{ entry: KbEntry }>("/knowledge/text", { method: "POST", body: JSON.stringify({ title, content, scope, agent_id }) });
export const deleteKb = (id: string) => req<{ ok: boolean }>(`/knowledge/${id}`, { method: "DELETE" });
export const uploadKb = async (file: File, scope: string, agentId: string, title: string) => {
  const fd = new FormData();
  fd.append("file", file); fd.append("scope", scope); fd.append("agent_id", agentId); fd.append("title", title);
  const token = getToken();
  const res = await fetch(`${API_BASE}/knowledge/upload`, { method: "POST", headers: token ? { Authorization: `Bearer ${token}` } : {}, body: fd });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `${res.status}`);
  return res.json();
};

// ---- supervisor strategy + coaching ---------------------------------------
export interface StrategicReview { id: string; created_at: string; observations: string[]; strategy: string; proposals: { id: string; agent_id: string; reason: string; status: string }[]; perf: Record<string, unknown> }
export const getStrategicReview = () => req<{ review: StrategicReview | null }>("/supervisor/strategic-review").then((r) => r.review);
export const runStrategicReview = () => req<{ review: StrategicReview }>("/supervisor/strategic-review", { method: "POST" }).then((r) => r.review);
export interface CoachingProposal { id: string; agent_id: string; reason: string; current_instructions: string; proposed_instructions: string; status: string }
export const getProposals = () => req<{ proposals: CoachingProposal[] }>("/supervisor/proposals").then((r) => r.proposals);
export const approveProposal = (id: string) => req<{ message: string }>(`/supervisor/proposals/${id}/approve`, { method: "POST" });
export const rejectProposal = (id: string) => req<{ ok: boolean }>(`/supervisor/proposals/${id}/reject`, { method: "POST" });

// ---- pipeline (lead-gen runs) ---------------------------------------------
export const getPipelineRuns = () => req<{ runs: PipelineRun[] }>("/pipeline/runs").then((r) => r.runs);

// ---- IT Technician health --------------------------------------------------
export interface Component { status: string; response_time_ms?: number; error?: string }
export interface ITHealth {
  overall: string; // ok | warning | risk | unknown
  checked_at: string;
  components: {
    claude_api: Component;
    mongodb: Component;
    smtp: Component;
    imap: Component;
    agents: { agent_id: string; name: string; status: string; stuck_since?: string; stuck_minutes?: number }[];
    error_spike?: { count_last_hour: number; spike: boolean };
  };
  explanation: string;
}
export const getItStatus = () => req<{ health: ITHealth }>("/it-monitor/status").then((r) => r.health);
export const runItCheck = () => req<{ health: ITHealth }>("/it-monitor/check", { method: "POST" }).then((r) => r.health);
