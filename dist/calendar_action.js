import { llmJson } from "./llm";
const CAL_BASE = process.env.CALENDAR_SERVICE_URL ?? "http://localhost:8787";
async function planCalendarAction(intent) {
    const now = new Date().toISOString();
    const system = `You turn a user's calendar request into a structured action. ` +
        `Today's date/time is ${now}. ` +
        `Return ONLY JSON matching: { "action": "create"|"update"|"delete"|"none", ` +
        `"title"?: string, "start_iso"?: string (no timezone offset), ` +
        `"duration_minutes"?: number, "location"?: string, "notes"?: string, ` +
        `"target_description"?: string }. ` +
        `Use "none" if this isn't actually a calendar create/update/delete request. ` +
        `For update/delete, "target_description" should describe which existing event is meant.`;
    return llmJson(system, intent);
}
async function findEventId(description, trace) {
    const res = await fetch(`${CAL_BASE}/events`);
    if (!res.ok)
        return null;
    const events = (await res.json());
    if (events.length === 0)
        return null;
    // Cheap heuristic match first; LLM disambiguation could replace this later.
    const lower = description.toLowerCase();
    const hit = events.find((e) => e.title.toLowerCase().includes(lower) ||
        lower.includes(e.title.toLowerCase()));
    if (hit)
        trace.push(`calendar: matched "${description}" -> "${hit.title}" (${hit.event_id})`);
    return hit?.event_id ?? null;
}
// Returns null if this doesn't look like a calendar action (so the router can
// try the next tier), or a RouteResult on success/failure of a real attempt.
export async function tryCalendarAction(intent, trace) {
    let plan;
    try {
        plan = await planCalendarAction(intent);
    }
    catch (e) {
        trace.push(`calendar: planning failed (${e.message})`);
        return null;
    }
    if (plan.action === "none") {
        trace.push("calendar: intent is not a calendar action");
        return null;
    }
    trace.push(`calendar: planned action="${plan.action}"`);
    try {
        if (plan.action === "create") {
            if (!plan.title || !plan.start_iso) {
                trace.push("calendar: missing title/start_iso for create — falling through");
                return null;
            }
            const res = await fetch(`${CAL_BASE}/events`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    title: plan.title,
                    start_iso: plan.start_iso,
                    duration_minutes: plan.duration_minutes ?? 60,
                    location: plan.location,
                    notes: plan.notes,
                }),
            });
            const body = await res.json();
            if (!res.ok)
                throw new Error(JSON.stringify(body));
            trace.push("calendar: event created");
            return { source: "calendar", status: "success", payload: body, trace };
        }
        if (plan.action === "delete" || plan.action === "update") {
            const targetDesc = plan.target_description ?? plan.title ?? intent;
            const eventId = await findEventId(targetDesc, trace);
            if (!eventId) {
                trace.push(`calendar: no matching event found for "${targetDesc}" — falling through`);
                return null;
            }
            if (plan.action === "delete") {
                const res = await fetch(`${CAL_BASE}/events/${eventId}`, {
                    method: "DELETE",
                });
                const body = await res.json();
                if (!res.ok)
                    throw new Error(JSON.stringify(body));
                trace.push("calendar: event deleted");
                return { source: "calendar", status: "success", payload: body, trace };
            }
            // update
            const res = await fetch(`${CAL_BASE}/events/${eventId}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    title: plan.title,
                    start_iso: plan.start_iso,
                    duration_minutes: plan.duration_minutes,
                    location: plan.location,
                    notes: plan.notes,
                }),
            });
            const body = await res.json();
            if (!res.ok)
                throw new Error(JSON.stringify(body));
            trace.push("calendar: event updated");
            return { source: "calendar", status: "success", payload: body, trace };
        }
        return null;
    }
    catch (e) {
        trace.push(`calendar: action failed (${e.message})`);
        return { source: "calendar", status: "failed", payload: null, trace };
    }
}
