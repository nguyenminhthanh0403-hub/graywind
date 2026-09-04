// Fires graywind's live-trading.yml on a schedule, bypassing GitHub Actions'
// own `schedule:` trigger entirely -- see wrangler.toml and
// ../.github/workflows/live-trading.yml's top-of-file comment for why.
// workflow_dispatch (a plain REST call) isn't subject to the same
// best-effort delay/drop behavior GitHub documents for `schedule:` events,
// so this Worker's own cron only needs to be reliable, not GitHub's.

async function triggerGraywindCycle(env) {
  const url = `https://api.github.com/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}/actions/workflows/${env.GITHUB_WORKFLOW_FILE}/dispatches`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_PAT}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "graywind-cron-trigger",
    },
    body: JSON.stringify({ ref: "main" }),
  });
  const bodyText = res.ok ? "" : await res.text();
  if (!res.ok) {
    console.error(`workflow_dispatch failed: ${res.status} ${bodyText}`);
  }
  return { ok: res.ok, status: res.status, bodyText };
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(triggerGraywindCycle(env));
  },

  // Manual GET lets you confirm the trigger works right now instead of
  // waiting for the next cron tick -- hit the Worker's *.workers.dev URL
  // directly. Treat that URL as effectively secret: anyone with it can
  // waste your Actions minutes by spamming dispatches, though they can't
  // do anything worse -- GITHUB_PAT never leaves this Worker.
  async fetch(request, env) {
    if (request.method !== "GET") {
      return new Response("not found", { status: 404 });
    }
    const result = await triggerGraywindCycle(env);
    return new Response(
      result.ok ? "dispatched" : `failed: ${result.status} ${result.bodyText}`,
      { status: result.ok ? 200 : 502 }
    );
  },
};
