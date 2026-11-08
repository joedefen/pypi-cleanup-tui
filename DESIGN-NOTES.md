You asked:
----------

I'm considering building a TUI that does what pypi-cleanup does, more or less. Now, I'm exploring the requirements. What about: presenting a 3-column table of "Delete Date Version" with a key to toggle the Delete status (and move to the next line). Maybe have two sorts (both reverse), one on Date and the other on version (numeric), and another key to execute the deletion (and refresh). What more seems needed or desirable?

---

DeepSeek Replied:
-----------------

Found 14 web pages

![](https://cdn.deepseek.com/site-icons/socket.dev)

![](https://cdn.deepseek.com/site-icons/github.com)

![](https://cdn.deepseek.com/site-icons/github.com)

Your three-column table with toggle, sort, and execute is a solid core interaction model. But for a tool that performs irreversible deletions on PyPI, the gap between "what you described" and "what is safe and usable" is significant. Here are the areas that most need attention.

### 🛡️ Safety and Confirmation Flow

The biggest risk with a TUI that deletes PyPI releases is a reflexive keypress causing irreversible damage. `pypi-cleanup` itself is aggressive about safeguards: it defaults to a dry-run, requires `--do-it` to actually delete, and in some modes demands an additional `--yes` flag as a "last chance to change your mind" .[\-1](https://socket.dev/pypi/package/pypi-cleanup#1)

Your TUI needs an equivalent **two-stage confirmation**:

1.  **Selection stage**: The user toggles Delete flags and sorts.
    
2.  **Execution stage**: Pressing your "execute" key should **not** immediately delete. It should transition to a confirmation screen or modal that summarizes exactly what will be deleted (e.g., "Delete 7 versions of `my-package`: 1.2.3, 1.2.4, ..."), requiring a distinct, non-adjacent keypress (like typing "YES" or pressing `Ctrl+Enter`) to proceed. This prevents accidental execution from a mistyped keybinding.
    

Additionally, a **query-only / read-only mode** is highly desirable. It lets users inspect their version history and plan a cleanup without ever entering credentials or risking a misclick .[\-1](https://socket.dev/pypi/package/pypi-cleanup#1)

### 🔐 Authentication and API Constraints

This is a hard technical requirement you must design around. **PyPI does not offer a REST API for deleting releases.** Historical methods relied on scraping and CSRF tokens from the web interface, but the mandatory rollout of 2FA for all PyPI accounts broke automated deletion scripts . The existing `pypi-cleanup` tool works by logging into the web interface with a username, password, and TOTP code to perform deletions .[\-1](https://socket.dev/pypi/package/pypi-cleanup#1)[\-4](https://github.com/linux-nvme/nvme-cli/blob/424b49ec47e9bf8730ed54f4e2a0880931b75ce0/libnvme/libnvme3/PUBLISHING.md)[\-8](https://github.com/pypi/warehouse/issues/12934)

Your TUI will likely need to do the same: interact with the web flow, handle a TOTP prompt, and manage session state. Plan for an authentication screen that accepts username, password, and a one-time code, and ensure credentials are never logged or stored in plaintext.

### 🎯 Selection and Bulk Operation Helpers

Manual row-by-row toggling becomes tedious for large projects. Consider adding helper actions bound to keys:

*   **Select all visible / deselect all**: Especially useful after applying a sort or filter.
    
*   **Invert selection**: Toggle the state of every visible row.
    
*   **"Leave most recent only"**: A one-key action that automatically toggles the Delete flag for every version except the latest, mirroring the `--leave-most-recent-only` flag in the CLI tool .[\-1](https://socket.dev/pypi/package/pypi-cleanup#1)[\-4](https://github.com/linux-nvme/nvme-cli/blob/424b49ec47e9bf8730ed54f4e2a0880931b75ce0/libnvme/libnvme3/PUBLISHING.md)
    

### 👁️ Row Context and Metadata

The three columns `Delete | Date | Version` are minimal. Users may need more context to make safe decisions:

*   **File count / Size**: A version with many files (e.g., wheels for multiple platforms) might be a larger storage win, but also more disruptive to delete.
    
*   **Pre-release indicator**: Visually distinguish `.dev`, `rc`, `a`, or `b` versions, as these are common cleanup targets.
    
*   **Project name**: If the TUI supports multiple packages (which is a desirable feature ), make it clear which project the versions belong to.[\-1](https://socket.dev/pypi/package/pypi-cleanup#1)[\-14](https://data.safetycli.com/packages/pypi/pypi-cleanup/changelog)
    

### 🔄 Post-Deletion Feedback and Refresh

After pressing the execute key and confirming, the TUI must:

1.  **Show progress**: Deleting releases is a series of network requests; display which version is being processed and any errors.
    
2.  **Report results**: A summary (e.g., "Successfully deleted 5 versions; 2 failed with HTTP 403").
    
3.  **Refresh state**: Automatically re-query the package's versions and rebuild the table, clearing the selection flags, so the user can verify the result and continue if needed.
    

### ⌨️ Discoverability and Navigation Polish

TUI users expect efficient keyboard navigation. Since you already plan to use arrow keys for movement, ensure:

*   **Vim-style bindings**: `j`/`k` for down/up, `g`/`G` for top/bottom.
    
*   **A persistent footer or help bar**: Display the active keybindings (`Space: Toggle | D: Sort Date | V: Sort Version | Enter: Execute | ?: Help`). Textual's `Footer` widget is designed for this .[\-13](https://zaloog.github.io/2025/02/26/tui-a-day.html?utm_source=hnblogs.substack.com)
    
*   **Sort indicators**: Clearly show which column is currently sorted and in which direction (e.g., a `▼` next to `Date`).
    

In short, your core idea is good, but the difference between a toy and a safe tool lies in the confirmation friction, the authentication reality of PyPI's web-only deletion, and the bulk-selection conveniences that save users from repetitive strain.

This response is AI-generated, for reference only.

![](https://cdn.deepseek.com/site-icons/socket.dev)

![](https://cdn.deepseek.com/site-icons/github.com)

![](https://cdn.deepseek.com/site-icons/github.com)

14 web pages

---

You asked:
----------

W/o a rest api, then I'd probably just drop out of my app, run pypi-cleanup and let it show whatever it shows when updating. It is such a hassle on the web to delete versions, that reducing that to one key seems "automation" enough. For example, I have projects that have perhaps 20 versions that I'd like to reduce to 1 or 2. My common TUI has the help bar, navigation, help screen, confirmation windows. And, while there might be projects with 100s or 1000s of version (I don't know), that is not the target. I like to see on the screen what will be kept and what is removed; maybe for mass deletions, a key to remove everything on the current line and below.

---

DeepSeek Replied:
-----------------

Found 26 web pages

![](https://cdn.deepseek.com/site-icons/pypi.org)

![](https://cdn.deepseek.com/site-icons/github.com)

![](https://cdn.deepseek.com/site-icons/socket.dev)

![](https://cdn.deepseek.com/site-icons/github.com)

Your instinct to shell out to `pypi-cleanup` is actually the right architectural call. Since PyPI has no deletion API and `pypi-cleanup` already handles the messy web authentication and TOTP flow, reimplementing that inside your TUI would be pure risk with no benefit . Your TUI becomes a **selection interface** that generates arguments for the existing tool, which is a much smaller and safer surface area.[\-2](https://github.com/linux-nvme/nvme-cli/blob/424b49ec47e9bf8730ed54f4e2a0880931b75ce0/libnvme/libnvme3/PUBLISHING.md)[\-8](https://github.com/ThalesGroup/agilab/blob/main/docs/pypi-cleanup-maintainer-guide.md#1)

Given your target scale (20-ish versions, not thousands), the "remove everything on current line and below" key is the one genuinely valuable addition you're missing. Here's what else is worth considering within that constrained scope:

### The "Truncate from Here" Key

Your proposed key is essentially a "keep only what's above this line" operation. This maps cleanly to your sort modes:

*   **Sorted by Date (reverse)**: The top rows are newest. Placing the cursor on the version you want to keep and pressing this key marks everything below for deletion.
    
*   **Sorted by Version (reverse)**: Same logic—top is highest version, bottom is oldest.
    

Implementation note: since your TUI won't delete directly, this key just toggles the Delete flag on all rows from the cursor downward. The user still sees the final selection on screen before pressing execute, which preserves your "see what will be kept and what is removed" requirement.

One safety detail: after this bulk toggle, the cursor should probably jump to the **first row that was just marked for deletion** (or stay put), so the user can visually verify the boundary. If they accidentally triggered it, a single toggle on the boundary row (or a "clear all flags" key) fixes it quickly.

### A "Clear All Deletions" Key

If you have "mark everything below," you need a fast undo for the selection state. A key that toggles all Delete flags back to false (or simply resets the entire column) prevents the user from having to manually un-toggle row by row if they change their mind. This is cheap to implement and directly supports the bulk-selection workflow.

### Pre-Flight Summary Before Shelling Out

Before your TUI runs `pypi-cleanup --do-it`, show a confirmation modal that lists the exact versions marked for deletion, not just a count. Since you're targeting small projects, this list will fit comfortably on screen. This catches the case where the user toggled flags, then changed the sort order, and lost track of what's actually selected. It also mirrors the "POSSIBLE DESTRUCTIVE OPERATION" warning that `pypi-cleanup` itself emits, so the user sees the same information twice from two independent sources .[\-1](https://pypi.org/project/pypi-cleanup/0.1.11/#1)

### Handling the Command Output

When you drop out of your TUI to run `pypi-cleanup`, you have a choice: suspend the TUI and let the subprocess write directly to the terminal, or capture the output and display it in a post-execution screen. For your scale, **suspending is simpler and more honest**—the user sees exactly what `pypi-cleanup` prints, including its own warnings and progress. On return, your TUI re-queries the package versions and refreshes the table. If you capture output instead, you risk truncating a warning or error that matters.

### What You Can Skip

*   **Regex filters**: `pypi-cleanup` supports `-r` patterns , but your TUI is for manual, visual selection. Adding a regex input field adds UI complexity and a second way to make a mistake. Skip it unless you find yourself repeatedly wanting to select all `dev` versions.[\-1](https://pypi.org/project/pypi-cleanup/0.1.11/#1)
    
*   **`--leave-most-recent-only` automation**: Your "truncate from here" key effectively covers this use case when sorted by date, and gives the user control over where the cut line falls.
    
*   **Multi-project support**: If your projects each have ~20 versions, switching projects by restarting the TUI or passing a project name as an argument is fine. A project switcher is polish, not a requirement.
    

The core insight from your plan: your TUI's job is to make **selection** pleasant, not to make **deletion** happen. `pypi-cleanup` already does the dangerous part. Your value-add is the visual table and the bulk-toggle ergonomics that the web interface lacks.

![](https://cdn.deepseek.com/site-icons/pypi.org)

![](https://cdn.deepseek.com/site-icons/github.com)

![](https://cdn.deepseek.com/site-icons/socket.dev)

![](https://cdn.deepseek.com/site-icons/github.com)

26 web pages

---

You asked:
----------

The pypi-cleanup tool is rather useless for getting the info with dates. How about: import datetime import requests def get\_package\_history(package\_name): url = f"https://pypi.org/pypi/{package\_name}/json" response = requests.get(url) if response.status\_code != 200: print(f"Package {package\_name} not found.") return data = response.json() releases = data.get("releases", {}) for version, files in releases.items(): if files: # Take the upload time of the first artifact in the release upload\_time = files\[0\].get("upload\_time") print(f"Version: {version:<12} Released: {upload\_time}") get\_package\_history("requests") --- are there restrictions on version names/numbers?

---

DeepSeek Replied:
-----------------

Found 14 web pages

![](https://cdn.deepseek.com/site-icons/python.org)

![](https://cdn.deepseek.com/site-icons/python.org)

![](https://cdn.deepseek.com/site-icons/pypi.org)

Yes, there are restrictions. PyPI itself does not impose a separate, proprietary set of naming rules; it relies on the Python packaging ecosystem's standard, which is **PEP 440**. For your TUI's purposes, the key takeaway is that you cannot assume all versions are simple numeric strings like `1.2.3`. They can contain letters, dots, and special suffixes.

### The Governing Standard: PEP 440

The authoritative specification for valid Python version identifiers is PEP 440 . Tools like `pip`, `setuptools`, and PyPI are designed to parse and compare versions according to this scheme.[\-1](https://packaging.python.org/en/latest/discussions/versioning/)[\-2](https://peps.python.org/pep-0440/)

A PEP 440-compliant version can include several components beyond a simple numeric release:

*   **Release segment**: The numeric part (e.g., `1.2.0`).
    
*   **Pre-release tags**: Such as `a` (alpha), `b` (beta), or `rc` (release candidate), e.g., `1.2.0rc1`.
    
*   **Post-release tags**: Such as `.post1` for a release that fixes metadata issues, e.g., `1.2.0.post1`.
    
*   **Development releases**: Such as `.dev1`, e.g., `1.2.0.dev1`.
    
*   **Epochs**: A rarely used prefix to fix sorting order, e.g., `1!1.0` (discouraged) .[\-1](https://packaging.python.org/en/latest/discussions/versioning/)
    

### Important Caveats for Your Code

Your current snippet simply prints the version string as returned by the API. This is fine for display, but you should be aware of two things:

1.  **Legacy Versions**: Historically, PyPI and `setuptools` tolerated "legacy" versions that do not strictly comply with PEP 440 (e.g., `2.4pl1`). While modern packaging tools strongly prefer PEP 440, you may still encounter older projects with non-compliant version strings .[\-5](https://setuptools.pypa.io/en/latest/userguide/distribution.html)[\-13](https://setuptools.pypa.io/en/stable/_sources/userguide/distribution.rst.txt)
    
2.  **Sorting is Non-Trivial**: If you plan to implement your own **numeric sort** on the version column, you cannot simply parse the string as a float. PEP 440 defines a specific ordering (e.g., `1.0.dev1` < `1.0a1` < `1.0b1` < `1.0rc1` < `1.0` < `1.0.post1`) . For robust sorting in your TUI, you should use the `packaging` library's `Version` class, which implements PEP 440 comparison logic, rather than writing your own parser.[\-5](https://setuptools.pypa.io/en/latest/userguide/distribution.html)
    

In short, you can treat the `version` field as a **string** for display, but if you need to **sort** by version, use a PEP 440-aware parser.

![](https://cdn.deepseek.com/site-icons/python.org)

![](https://cdn.deepseek.com/site-icons/python.org)

![](https://cdn.deepseek.com/site-icons/pypi.org)

14 web pages

---

You asked:
----------

I notice that pypi-cleanup has only way to specify versions to remove, regex. So, I'm just supposed to build a string like '^(1.2|2.3b1|2.0.5)$' to remove those 3 releases? Is this tool built as a "backend" to something nicer?

---

DeepSeek Replied:
-----------------

Found 23 web pages

![](https://cdn.deepseek.com/site-icons/github.com)

![](https://cdn.deepseek.com/site-icons/github.com)

![](https://cdn.deepseek.com/site-icons/socket.dev)

![](https://cdn.deepseek.com/site-icons/github.com)

Yes, your understanding is correct: if you want to precisely delete those 3 specific versions, you need to construct such a regex string and pass it to `pypi-cleanup` via `-r`/`--version-regex`.[\-3](https://socket.dev/pypi/package/pypi-cleanup/overview/0.1.6/tar-gz#1)[\-11](https://socket.dev/pypi/package/pypi-cleanup#1)[\-14](https://pypi.org/project/pypi-cleanup/0.1.11/#1)

As for whether it is "a backend for a better tool"—it's not designed that way by default, but your approach of using it as a backend is actually quite reasonable.

### 🎯 Regex is the Only Precise Selection Method

`pypi-cleanup` has no concept of a "version list." Its selection logic is to use `re.match` to check each version string against the regex you provide, and any match gets selected. So if you want to delete `1.2`, `2.3b1`, and `2.0.5`, the regex you wrote `^(1.2|2.3b1|2.0.5)$` is indeed the correct approach (using `^` and `$` to anchor the entire string, preventing `1.2` from accidentally matching `1.2.3`).[\-21](https://www.codedocs.xyz/CoolProp/CoolProp/namespacetestpypi__prune.html#ae7f293cdc914886f6c58d9f052307b75)

Besides regex, it only has two non-precise bulk modes:

*   **Default pattern**: `.*dev\d+$`, which deletes all development versions ending with `.dev` plus a number.[\-13](https://pypi.org/project/pypi-cleanup/0.0.1/#1)[\-14](https://pypi.org/project/pypi-cleanup/0.1.11/#1)
    
*   **`--leave-most-recent-only`**: deletes all versions except the most recent one based on file upload time.[\-3](https://socket.dev/pypi/package/pypi-cleanup/overview/0.1.6/tar-gz#1)[\-11](https://socket.dev/pypi/package/pypi-cleanup#1)
    

Neither of these can help you "precisely retain 1-2 versions while deleting the rest"—you have to rely on regex.

### 🔗 There Are Precedents for Using It as a Backend

You're not the first to use it this way. Some projects' CI scripts (such as CoolProp) do exactly this: first use a Python script to call the PyPI JSON API to get the version list, calculate which versions to delete, **dynamically generate an anchored regex string**, and then pass it to `pypi-cleanup -r` to execute.[\-21](https://www.codedocs.xyz/CoolProp/CoolProp/namespacetestpypi__prune.html#ae7f293cdc914886f6c58d9f052307b75)

So your TUI architecture is completely viable: **your TUI is responsible for the visual selection of "which versions to delete," then concatenates the selected version numbers with `|`, wraps them with `^(...)$`, and passes them to `pypi-cleanup`**.

### 💡 A Small Reminder

The regex matching is against PyPI's **normalized version numbers** (from `/simple/`), not the original keys in the JSON API. For the vast majority of versions, these are the same, but occasionally edge cases (like underscores vs. hyphens) may differ. The versions you saw when fetching via `/pypi/{package}/json` may not be exactly identical to the version strings used internally for matching in `pypi-cleanup`, so it's worth keeping in mind.

![](https://cdn.deepseek.com/site-icons/github.com)

![](https://cdn.deepseek.com/site-icons/github.com)

![](https://cdn.deepseek.com/site-icons/socket.dev)

![](https://cdn.deepseek.com/site-icons/github.com)

23 web pages

---

You asked:
----------

I'm trying to pick a name for the project ... how about pypi-nuke?

---

DeepSeek Replied:
-----------------

`pypi-nuke` is memorable and clearly communicates "destructive bulk operation," which is honest about what the tool does. A few things to weigh before committing:

### Potential Concerns

**Name collision and searchability.** There's an existing `pypi-cleanup` and various `pypi-*` tools. "Nuke" is a common metaphor in CLI tools (e.g., `nuke` build systems, AWS nuke tools), so `pypi-nuke` may be hard to find in search results and could collide with an existing package name on PyPI. Check `https://pypi.org/project/pypi-nuke/` before you invest in the name.

**Tone vs. safety.** Your tool's core value is _careful visual selection_ before handing off to `pypi-cleanup`. "Nuke" signals recklessness, which is slightly at odds with the confirmation-modal, see-what-you-keep design you described. That's a minor branding tension, not a blocker—many tools use aggressive names while being careful internally (e.g., `ripgrep` is fast and precise, not destructive).

**Trademark adjacency.** "Nuke" is strongly associated with Foundry's Nuke compositing software. For a small open-source TUI this is almost certainly fine, but it's worth knowing.

### Alternatives Worth Considering

| Name | Vibe | Notes |
| --- | --- | --- |
| `pypi-prune` | Gardening metaphor | Suggests selective removal, fits "keep 1-2 versions" use case |
| `pypi-trim` | Light, precise | Implies cutting excess without violence |
| `pypi-sweep` | Cleaning | Neutral, action-oriented |
| `pypi-cleanup-tui` | Explicit | Signals it's a frontend to `pypi-cleanup`; boring but unambiguous |
| `pypi-reaper` | Destructive but controlled | "Grim reaper" implies deliberate selection |
| `pypi-cull` | Selective removal | Culling is exactly "remove the weak, keep the strong" |

### My Take

If your target audience is you and a handful of people who already know what the tool does, `pypi-nuke` is fine—it's punchy and you'll remember it. If you want the name to signal the _careful selection_ workflow (which is your actual differentiator), `pypi-prune` or `pypi-cull` better capture "I chose what dies" rather than "everything dies."

One practical suggestion: pick the name, then write the one-line description. If the description reads "A TUI for selectively deleting PyPI release versions," `pypi-nuke` creates a small mismatch. If it reads "Nuke old PyPI releases from a terminal," it's consistent. Either is defensible—just make the choice deliberately.

---

You asked:
----------

I think pypi-cleanup-tui seems like the killer name ... it can be aliased to shorten ;-)

---

DeepSeek Replied:
-----------------

That name is the right call, and for a specific reason: it makes the **dependency relationship legible**. Anyone who finds `pypi-cleanup-tui` immediately understands it's a frontend to `pypi-cleanup`, which sets correct expectations about authentication, the underlying deletion mechanism, and the fact that it's not reimplementing the web flow. That's a meaningful trust signal for a tool that deletes things irreversibly.

It also sidesteps the searchability problem I raised earlier—`pypi-cleanup` already has mindshare, and a name that extends it inherits that discoverability rather than competing with it.

### On the Alias

The alias is where you get to have the punchy name without the branding mismatch. Common patterns:

*   `pct` — short, but collides with "pct" (percent) and possibly other tools
    
*   `pcu` — reasonably distinct, easy to type
    
*   `pclean` — readable, less ambiguous
    
*   `pypi-tui` — too generic
    

Whatever you pick, document it prominently and consider shipping the console script entry point under both names so `pip install pypi-cleanup-tui` gives users the long name and the alias without extra setup. That's cheap to do in `pyproject.toml`:

toml

Copy

Download

\[project.scripts\]
pypi-cleanup-tui \= "pypi\_cleanup\_tui.app:main"
pcu \= "pypi\_cleanup\_tui.app:main"

### One Naming Detail

If you go this route, make sure your README's first paragraph states the relationship explicitly—"A terminal UI for selecting which PyPI releases to delete, built on top of `pypi-cleanup`"—so nobody installs it expecting an independent implementation and then wonders why they need `pypi-cleanup` installed alongside it. You may even want to make `pypi-cleanup` a declared dependency so the shell-out always works, rather than failing at execute time with a "command not found."

Good name. It's honest about what the tool is and what it isn't, which is exactly what you want for something that presses the delete button.

---

