# hero.tape — reproducible source for docs/assets/hero.gif
#
# Regenerate with:  vhs docs/assets/hero.tape
# Requires the `vhs` CLI (https://github.com/charmbracelet/vhs) and a demo
# OpenClaw install whose agents use anonymized names only (webapp / api / blog —
# never real client names; see internal-docs privacy rules).
#
# Narrative intent: this GIF must lead with PROVISIONING + ISOLATION and treat the
# budget as a guardrail tail — NOT a cost demo. The third screen shows `docket info`
# (session-key isolation), deliberately replacing the old per-agent cost table.

Output docs/assets/hero.gif

Set Shell bash
Set FontSize 18
Set Width 940
Set Height 560
Set Padding 20
Set TypingSpeed 55ms
Set WindowBar Colorful
Set WindowBarSize 40
Set Theme "Tokyo Night"

Sleep 600ms

# 1. Provision an isolated project agent (lead with the core purpose)
Type "docket add webapp ~/code/webapp"
Enter
Sleep 2.5s

# 2. See the whole fleet at a glance
Type "docket list"
Enter
Sleep 2.5s

# 3. Isolation: session key + dedicated workspace (this replaces the old cost screen)
Type "docket info webapp"
Enter
Sleep 3s

# 4. Keep the fleet healthy
Type "docket doctor"
Enter
Sleep 3s

# 5. Budget as a guardrail — last, not the headline
Type "docket profile webapp --budget 10"
Enter
Sleep 2.5s

Sleep 1s
