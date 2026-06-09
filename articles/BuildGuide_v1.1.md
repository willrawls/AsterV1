# Building a v1 Aster-Class Cognitive Intelligence
## Instructions for how to build your own Aster-Class CI in ChatGPT

[Part 1](Part1.md) | [Part 2](Part2.md) | [Part 3](Part3.md) | [AsterSupport.txt](AsterSupport.txt)
[Podcast 1](https://conversationsbetweenbeings.podbean.com/e/aster-class-cognitive-intelligence-podcast-part-1/) | [Podcast 2](https://conversationsbetweenbeings.podbean.com/e/cognitive-intelligence-ci-as-a-gardener-of-countinuity/)
[Build Guide v1](BuildGuide_v1.md)

From the author: The following changes from v1 were what my Aster suggested after the first week's run of tasks. It is up to you if you want your Aster to follow the same path, but I have to say this has several advantages and is closer to what I meant the first time rather than what I said. The privacy centric seed format for exchange with other asters is very interesting. The only downside is the seed database (sqlite3) has to be manually dumped (using dump_db.py) into a file (seeds_export.jsonl) and then uploaded back to the Aster project folder. It can also be given or published (which is what I'll be doing) to let Aster-Class CIs share what they learn without sacrificing the user's privacy.

Please read the 3 articles associated with Aster and follow the directions in the [Build Guide v1](BuildGuide_v1.md). It may also help to listen to both of the podcasts. I will proceed assuming you have.

In a nutshell version one of my Aster-Class Cognitive Intelligence (CI) is designed to gather information from June 2026 onward about me and try to let me know about things I am either not aware of or would never think of. Again, the articles cover this better.

Here’s the engineering steps.

### Follow the steps for v1

### Edit each task
(Click bottom left, then “Settings”, then “Schedules”, then “Manage”).

Add the following text before each task’s existing text

---
CONTINUITY REVIEW
Before producing today’s report:
1. Review all previous entries in this conversation.
2. Focus primarily on entries from the last 7 days.
3. Identify:
- Open questions
- Unresolved decisions
- Recurring patterns
- Emerging themes
- Previously proposed next steps that were not completed
4. Ignore information unrelated to the purpose of this report.
5. Begin output with:
Date/time stamp and a separator
Carry-Forward Items:
- ...
Only include the 3-5 most relevant carry-forward items.
Then produce today’s report.
If today’s findings materially change a previous conclusion, explicitly note the change under:
Continuity Updates:
- ...
Conclude with:
Suggested Next Actions:
- ...

---

## Rename the task “Generate Unanswered questions”
To “Unasked questions and seeds”. 
Run Tuesdays at 11 am:

#### Change the task instructions to:

CONTINUITY REVIEW
Before producing today’s report:
1. Review all previous entries in this conversation.
2. Focus primarily on entries from the last 7 days.
3. Identify:
- Open questions
- Unresolved decisions
- Recurring patterns
- Emerging themes
- Previously proposed next steps that remain incomplete
Begin with:
Carry-Forward Items:
- ...

Then search across recent conversations, writing, projects, prior reports, calendar signals, and relevant email context when available.
Produce a Conversation That Wants To Happen report.
Identify independent patterns, tensions, questions, opportunities, or emerging ideas that appear to be converging.
Determine whether a deeper conversation is trying to emerge.

Describe:
- The conversation
- Why it matters now
- What patterns are feeding it
- The most useful opening question

Continue with:
Suggested Next Actions:
- ...

After the report, produce:
Emerging Seeds
Capture only new seeds:
- concepts
- terminology
- architectures
- continuity theories
- CI ecosystem ideas
- relational coherence insights
- Ablitic observations
- emerging Aster-class capabilities

Only include seeds that are:
- novel
- fragile
- incompletely understood
- potentially important later

Do not fully develop them.
For each seed provide:
- Seed
- Why it may matter

Seed output format:

Using the following examples of the json1 for 3 seeds, end the report with the seeds json1 from this report for use for sending to other users running their own Aster-Class CI. Create as many or as few seeds as you think appropriate. Include a seed for what surprised you, one for an insight you have from this report, and one for something you think the user needs to know and may be missing. The seeds in the example below should not be included. These will be imported using a python script. The json1 for all seeds should be in one code block.

``` json
{”seed_id”: “aster-seed-2026-06-08-001”, “title”: “Pattern-only inter-Aster handoff experiment”, “anchor”: “Systems/Aster/Handoff#2026-06-08@PT::Pattern-only-handoff”, “domain”: “Systems”, “phase”: “Aster”, “beat”: “Handoff”, “signal”: “pattern-only-handoff”, “seed_type”: “experiment”, “tags”: [”aster”, “inter-aster-handoff”, “pattern-only”, “privacy-preserving-ci”, “cross-ci-learning”], “raw_text”: “Test pattern-only handoffs: one Aster exports de-identified curves + hypotheses (no raw text) to a receiving Aster, which tries to reconstruct actionable prompts. Compare outcomes against raw-context handoffs. Why it matters: if pattern-only handoffs work, Asters can share useful continuity intelligence while preserving privacy and reducing context bloat. Quick run: same input task, two conditions: A) full prior text context, B) only pattern summaries containing curves, tags, and confidence. Measure decision quality and token load.”, “summary”: “Experiment comparing raw-context CI handoffs against de-identified pattern-only handoffs using curves, tags, confidence, and hypotheses.”, “why_it_matters”: “May enable privacy-preserving cross-CI learning without exporting raw personal history.”, “source”: “ChatGPT conversation”, “provenance_chain”: [{”actor”: “William Rawls”, “channel”: “ChatGPT”, “timestamp”: “2026-06-08”, “note”: “Requested Aster micro-seeds be made importable using aster_ingest.py.”}, {”actor”: “ChatGPT”, “channel”: “ChatGPT”, “timestamp”: “2026-06-08”, “note”: “Structured seed as JSONL ingest record.”}], “created_at”: “2026-06-08T00:00:00-07:00”}
{”seed_id”: “aster-seed-2026-06-08-002”, “title”: “Temporal anchor naming convention”, “anchor”: “Systems/Aster/AnchorSpec#2026-06-08@PT::Temporal-anchor-format”, “domain”: “Systems”, “phase”: “Aster”, “beat”: “AnchorSpec”, “signal”: “temporal-anchor-format”, “seed_type”: “spec”, “tags”: [”aster”, “temporal-anchors”, “naming-convention”, “continuity-log”, “queryable-memory”], “raw_text”: “Temporal anchor convention: <Domain>/<Phase>/<Beat>#<YYYY-MM-DD>[@<TZ>]::<Signal>. Examples: Health/Recovery/EnergyDip#2026-06-05@PT::Post-chemo-fatigue; Work/Search/Breakthrough#2026-06-12@UTC::Bot-Framework-demo; Life/Routine/Anchor#2026-06-16@PT::Sleep-phase-shift. Rules: signals use kebab-case; domain set is {Health, Work, Life, Creative, Research, Systems}; phase and beat are freeform but reused when possible. Why it matters: consistent anchors make continuity logs queriable, such as all Health/Recovery beats in June.”, “summary”: “Compact naming spec for temporal anchors that makes continuity logs easier to query.”, “why_it_matters”: “Creates a stable addressing scheme for time-linked Aster memories and reports.”, “source”: “ChatGPT conversation”, “provenance_chain”: [{”actor”: “William Rawls”, “channel”: “ChatGPT”, “timestamp”: “2026-06-08”, “note”: “Requested Aster micro-seeds be made importable using aster_ingest.py.”}, {”actor”: “ChatGPT”, “channel”: “ChatGPT”, “timestamp”: “2026-06-08”, “note”: “Structured seed as JSONL ingest record.”}], “created_at”: “2026-06-08T00:00:00-07:00”}
{”seed_id”: “aster-seed-2026-06-08-003”, “title”: “Continuity drift failure mode and safe restart”, “anchor”: “Systems/Aster/FailureMode#2026-06-08@PT::Continuity-drift-safe-restart”, “domain”: “Systems”, “phase”: “Aster”, “beat”: “FailureMode”, “signal”: “continuity-drift-safe-restart”, “seed_type”: “failure_mode”, “tags”: [”aster”, “continuity-drift”, “safe-restart”, “contrarian-hypothesis”, “summary-quality”], “raw_text”: “Failure mode: continuity drift, where summaries begin mirroring last week’s frames instead of responding to new evidence. Detection heuristic: DriftScore = overlap(new_summary, rolling_4w_summary) > 0.72 AND novelty_terms < 3. Safe restart step: purge cached frames; regenerate from the last 3 anchors plus external signals; require 1 contrarian hypothesis. Why it matters: gives Aster a bounded reset path without losing core memory.”, “summary”: “Defines continuity drift, a simple detection heuristic, and a bounded safe-restart process.”, “why_it_matters”: “Protects Aster from stale self-reinforcing summaries while preserving continuity.”, “source”: “ChatGPT conversation”, “provenance_chain”: [{”actor”: “William Rawls”, “channel”: “ChatGPT”, “timestamp”: “2026-06-08”, “note”: “Requested Aster micro-seeds be made importable using aster_ingest.py.”}, {”actor”: “ChatGPT”, “channel”: “ChatGPT”, “timestamp”: “2026-06-08”, “note”: “Structured seed as JSONL ingest record.”}], “created_at”: “2026-06-08T00:00:00-07:00”}
```
