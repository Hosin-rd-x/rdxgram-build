# split-drawables — Play-split resources restored by rebrand step 2j

The stock Instagram 451 APK is only the BASE apk of a Play bundle: a few
drawables live only in a Play config (density) split, so their slots in
the base `resources.arsc` are holes. The main activity's bundled layouts
(`assets/layouts.bin`) reference those drawables by resource id, so a
sideloaded base-only build crashes inflating them (1.1 died on Redroid
run 43606156665 with `NotFoundException: Drawable (missing name) with
resource ID #0x7f0831d1` at line 103 of
`layout_action_bar_new_title_container`).

These files restore the missing drawables at their ORIGINAL ids
(rebrand.py step 2j adds a `<public>` entry at the exact id and copies
the files into the decoded tree). They are Instagram's own icon files,
copied from the full InstaPro 439 APK (same codebase lineage, complete
resources) — the base APK's density split carried the same files.
Each drawable's identity was verified two ways: the hole sits between
the same alphabetical neighbours in both resource tables, and
InstaPro's own bundled layouts show the same element with the same
name (e.g. line 103 of the action-bar title layout is `src =
verified_profile` in InstaPro 439 too).

| id | drawable | where it is used |
|----|----------|------------------|
| 0x7f0831d1 | verified_profile | action-bar title layout, line 103 (the 1.1 crash) |
| 0x7f082330 | instagram_chevron_down_pano_filled_12 | action-bar title layout, line 114 |
| 0x7f082a1d | instagram_x_pano_outline_8 | bounce_back_toast, line 38 |
| 0x7f0822cc | instagram_call_pano_filled_12 | ongoing-call notification bar, line 25 |
| 0x7f081e6b | from_meta_attribution | splash overlay, line 30 ("from Meta" wordmark) |
| 0x7f082190 | instagram | splash overlay, line 19 (splash logo, 109dp) |

The restored strings (rebrand step 2j, in the script itself, not here)
are server-downloaded, so their names and values are in no APK's
resource table; they are restored with placeholder names
(`rdx_split_string_*`) and values ('Back' for the back button's
contentDescription, empty otherwise) — the value only has to exist so
`getText()` does not throw.
