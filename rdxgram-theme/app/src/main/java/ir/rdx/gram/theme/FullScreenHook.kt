package ir.rdx.gram.theme

import android.app.Activity
import android.graphics.Color
import android.graphics.drawable.ColorDrawable
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.FrameLayout
import java.util.Collections
import java.util.WeakHashMap

/**
 * Full-screen feed for RdxGram 1.18 (on top of the proven-clean 1.17.1).
 *
 * What Hossein asked for (confirmed from his phone photo):
 *  - the feed extends behind the status bar at the top and behind the
 *    capsule at the bottom;
 *  - the status icons (clock / battery / signal) STAY, with only a very
 *    light soft veil behind them;
 *  - the bottom gesture-line area is FULLY transparent — no feed blur,
 *    just the capsule with its liquid-glass look;
 *  - behind the capsule itself is FULLY TRANSPARENT (not blurred), so
 *    the feed shows through untouched around it.
 *
 * Honest limit, stated plainly: there is NO real backdrop blur here.
 * View.setRenderEffect blurs a view's OWN content, not what is behind
 * it, and Android offers no public API to blur arbitrary app content
 * behind a view. What this hook does instead:
 *  - a very light top gradient scrim (barely-there dark fade, ~15% black
 *    at the very top fading to transparent over the status-bar height
 *    plus a little) laid over the content as a non-touchable decor child,
 *    with a transparent status bar and content laid out to y=0 — the
 *    lightest honest equivalent of a "soft blur" behind the icons;
 *  - fully transparent status + navigation bars, content laid out under
 *    both (FLAG_LAYOUT_FULLSCREEN / FLAG_LAYOUT_HIDE_NAVIGATION);
 *  - the feed pager's bottom padding neutralised and its height grown
 *    to fill its container, so feed content scrolls UNDER the capsule;
 *  - Instagram's own 1px tab_bar_shadow divider and its floating
 *    gradient strip behind the bar hidden, so nothing but the capsule
 *    sits over the feed at the bottom.
 *
 * == Why 1.13–1.17.1 did NOT work (read before touching this file) ==
 *
 * The old code cleared the TOP PADDING of layout_container_main_wrapper,
 * expecting the content to rise to y=0. It never did — every probe dump
 * (1.13, 1.15, 1.16, 1.17, 1.17.1) shows the panel, the wrapper, the
 * container and the pager all still starting at y=48. Padding cannot
 * move a view: padding lives INSIDE the view and never moves its top
 * edge. The 48 px is a LAYOUT position, not padding.
 *
 * The real hierarchy (1.17.1 re-probe #2 dump, ui_step05.xml, 720x1280):
 *   android:id/content            [0,0][720,1280]   (full height already)
 *   swipe_navigation_container    [0,0][720,1280]
 *   layout_container_center_right_coordinator_layout [0,0][720,1184]
 *   layout_container_main_panel   [0,48][720,1184]   <- FIRST view at y=48
 *   layout_container_main_wrapper [0,48][720,1184]
 *   layout_container_main         [0,48][720,1088]
 *   swipeable_tab_view_pager      [0,48][720,1088]
 * Every ancestor above the panel starts at y=0, so the 48 px (exactly
 * the status-bar height, 24dp) is applied AT the panel: either as the
 * panel's own top margin (set by Instagram's code), as top padding on
 * the coordinator (fitsSystemWindows), or by a CoordinatorLayout
 * Behavior seating the child. This version moves the PANEL itself —
 * top margin to 0, any Behavior removed, any ancestor top padding
 * cleared — and only then is the wrapper's own top padding cleared
 * (harmless when already 0). The tab bar is bottom-anchored inside
 * the wrapper, so moving the panel up does NOT move the capsule: the
 * panel keeps its full height (MATCH_PARENT in its 1184-tall parent)
 * and the bar stays at [32,1072][688,1168].
 *
 * The bottom half has its own disease. The pager is
 * [0,48][720,1088] — the wrapper's height (1136) minus one
 * tabBarHeight (96 px) — while the wrapper is a plain IgFrameLayout
 * (117-line smali, no onMeasure/onLayout override), so nothing in the
 * parent caps it: Instagram sets the pager's height itself, and the
 * old growToParent (MATCH_PARENT, guarded so it ran once) was undone
 * by Instagram resetting the height on tab switches. The shadow-hide
 * in the same hook DID work (the shadow is gone from 1.15+ dumps but
 * present in 1.14), which proves applyGeometry runs and findByName
 * works — only the height assertion lost. This version therefore
 * re-asserts the height on the pager's OWN layout changes (a
 * layout-change listener, guarded on the layout-params VALUE so it
 * can never loop) and escalates to an explicit fixed height equal to
 * the parent's measured height when MATCH_PARENT demonstrably does
 * not stick. Every step logs what it changed, so the probe can tell
 * which mechanism was at work.
 *
 * Geometry is set by CODE, not XML: the tabBarHeight attribute
 * (0x7f040d3e) has NO value in the resource table, and the pager /
 * container heights are set per-tab by Instagram's own code — so this
 * is a runtime hook in the theme module, same pattern as TabBarHook.
 * apply() runs on every debounced sweep (TabBarHook.sweep), so
 * anything Instagram resets is re-asserted within ~400 ms.
 *
 * 1.19 (on top of the proven-clean 1.18) — Hossein's phone verdict:
 *  - headers/toolbars collided with the status icons (feed "For you",
 *    reels "For you / Friends", profile "hosinrdxpro", direct inbox):
 *    the panel moved up but the chrome stayed at y=0. insetTopChrome
 *    pushes every top bar down by exactly the status-bar height and
 *    shifts the content below it by the same amount; the media itself
 *    stays full-bleed from y=0 and still scrolls under the bars.
 *  - the reels caption (clips_media_info_component) and the action
 *    rail (clips_ufi_component) ended 30 px INSIDE the capsule zone;
 *    raiseReelChrome lifts them so their bottoms sit 8dp above the
 *    capsule top, measured live against the bar's real position.
 *  - a thin white line survived at the very bottom: the feed ended at
 *    y=1184 and the window background (white) showed through the
 *    transparent nav bar. The coordinator is grown to the true bottom
 *    (1280) and the window/decor background is set black, so the
 *    strip is feed content — or black, never white.
 *    (1.19.1 correction: that theory proved wrong — the strip stayed
 *    light in the 1.19 re-probe #2 screenshots. See below.)
 * 1.19.1 (on top of 1.19) — the white strip's real painter:
 *  - the 1.19 re-probe #2 dumps name it: a framework view with id
 *    android:id/navigationBarBackground, a direct child of the decor,
 *    sitting at exactly [0,1184][720,1280] — the strip, to the pixel.
 *    The window attribute window.navigationBarColor = TRANSPARENT
 *    (set on every sweep) never reaches it on this build, and the
 *    black window/decor/content backgrounds never show because this
 *    view sits above them and paints the strip light itself.
 *    blackenNavBarBackground recolors the VIEW itself, every sweep —
 *    but only when its current background is an opaque light colour
 *    (alpha >= 200, luminance > 128). The same view is present at the
 *    same bounds in the Reels dump, where it is transparent and the
 *    video fills to the bottom — so the guard is what keeps Reels
 *    full-bleed: transparent and already-dark backgrounds are left
 *    untouched, and a blackened view never matches the predicate
 *    again, so a settled state is a no-op.
 *  - the top scrim is now a smoother 5-stop fade ending just below
 *    the status icons (statusBarHeight + 12dp), still very light.
 *
 * Conservative by design: every step is null-checked and wrapped in
 * its own try/catch, so a missing view (or a view Instagram rebuilt
 * mid-swipe) can never crash the app — that step is skipped and the
 * rest still runs. Original margins / heights / paddings /
 * visibilities are saved the first time they are changed, so a future
 * restore can put them back. A value is only ever written when it
 * actually differs, so a settled layout is a no-op and can never
 * loop.
 */
object FullScreenHook {

    // View tag (module-local key) for the top scrim, stored on the decor view.
    private const val TAG_TOP_SCRIM = 0x7e1e0311
    // 1.19: set on the decor once the black window background is
    // applied — apply() runs on every sweep, and re-setting the
    // window background every ~400 ms would invalidate the whole
    // window each time (visible churn on a smooth feed).
    private const val TAG_BLACK_BG = 0x7e1e0312

    // Decors already given the window flags (weak keys: a dead decor drops out).
    private val flaggedDecors: MutableSet<View> =
        Collections.newSetFromMap(WeakHashMap<View, Boolean>())

    // Original values, saved on first change (weak keys: dead views drop out).
    private val savedPaddings: MutableMap<View, IntArray> =
        Collections.synchronizedMap(WeakHashMap<View, IntArray>())
    private val savedVisibility: MutableMap<View, Int> =
        Collections.synchronizedMap(WeakHashMap<View, Int>())
    private val savedMargins: MutableMap<View, IntArray> =
        Collections.synchronizedMap(WeakHashMap<View, IntArray>())
    private val savedHeights: MutableMap<View, Int> =
        Collections.synchronizedMap(WeakHashMap<View, Int>())

    // One-shot state, so a confirmation / removal is logged once per view
    // instance instead of on every sweep (weak keys: dead views drop out).
    private val panelTopConfirmed: MutableSet<View> =
        Collections.newSetFromMap(WeakHashMap<View, Boolean>())
    private val behaviorChecked: MutableSet<View> =
        Collections.newSetFromMap(WeakHashMap<View, Boolean>())
    private val fitsCleared: MutableSet<View> =
        Collections.newSetFromMap(WeakHashMap<View, Boolean>())
    private val pagerListenerAttached: MutableSet<View> =
        Collections.newSetFromMap(WeakHashMap<View, Boolean>())
    private val pagerHeightConfirmed: MutableSet<View> =
        Collections.newSetFromMap(WeakHashMap<View, Boolean>())
    private val escalationCapped: MutableSet<View> =
        Collections.newSetFromMap(WeakHashMap<View, Boolean>())

    // 1.19.1: views whose navigationBarBackground state was logged once
    // (no background drawable, or a background that is not a plain
    // colour) — so the sweep does not spam the log every ~400 ms.
    private val navBarBgLogged: MutableSet<View> =
        Collections.newSetFromMap(WeakHashMap<View, Boolean>())

    // 1.19: the bottom inset the coordinator loses to the system nav
    // bar (parent height − coordinator height, 96 px on the 720x1280
    // probe). Measured ONCE, before the coordinator is grown, and
    // kept sticky: after growth the difference reads 0. TabBarHook
    // adds it to the bar's bottom margin so the capsule does not
    // slide down when the coordinator grows to the true bottom.
    // Written on the main thread (sweep); read on the same thread.
    @Volatile
    var bottomInsetPx: Int = 0

    // 1.19: chrome shifts (headers + the content below them).
    // ChromeShift.mode: 0 = top margin (preferred — composes with
    // Instagram's own translationY hide/show animations instead of
    // fighting them), 1 = translationY fallback (used only when the
    // next sweep measures that the margin did not move the view —
    // some parents position children without honouring margins).
    // origLayoutTop is the window top the view had before any shift
    // (0 for a header, the header's height for the content below it);
    // sweepsSeen counts maintain passes so a margin gets one full
    // layout cycle to prove itself before the mode switches.
    private class ChromeShift(
        var origMargin: Int,
        var mode: Int,
        val targetTop: Int,
        var origLayoutTop: Int,
        val isHeader: Boolean,
        var sweepsSeen: Int = 0
    )

    private val chromeShifts: MutableMap<View, ChromeShift> =
        Collections.synchronizedMap(WeakHashMap<View, ChromeShift>())

    // 1.19: original top padding of the feed list (android:id/list),
    // so the header inset below is applied exactly once.
    private val savedListTopPadding: MutableMap<View, Int> =
        Collections.synchronizedMap(WeakHashMap<View, Int>())

    /** Apply the full-screen treatment to this activity. Idempotent; safe to call often. */
    fun apply(a: Activity?) {
        if (a == null) return
        try {
            applyWindow(a)
        } catch (ignored: Throwable) {
        }
        try {
            applyGeometry(a)
        } catch (ignored: Throwable) {
        }
    }

    // -- window: transparent bars, content laid out under them ----------------

    private fun applyWindow(a: Activity) {
        val window = a.window ?: return
        try {
            window.addFlags(WindowManager.LayoutParams.FLAG_DRAWS_SYSTEM_BAR_BACKGROUNDS)
            window.statusBarColor = Color.TRANSPARENT
            window.navigationBarColor = Color.TRANSPARENT
        } catch (ignored: Throwable) {
        }
        try {
            // 1.19: the window background is what shows wherever no
            // content reaches (the 96 px strip below the feed in
            // 1.18, pure white in the probe screenshots). Black, so
            // any such sliver reads as empty dark space, never a
            // white line. The decor and the content view get the same
            // treatment — one of them is the layer the strip shows.
            // Once only per decor (guarded by a tag): apply() runs on
            // every sweep and re-setting these every ~400 ms would
            // invalidate the whole window each time.
            val decorForBg = window.decorView
            if (decorForBg != null && decorForBg.getTag(TAG_BLACK_BG) == null) {
                val black = android.graphics.drawable.ColorDrawable(Color.BLACK)
                window.setBackgroundDrawable(black)
                decorForBg.setBackgroundColor(Color.BLACK)
                val content = a.findViewById<View>(android.R.id.content)
                if (content != null) content.setBackgroundColor(Color.BLACK)
                decorForBg.setTag(TAG_BLACK_BG, true)
            }
        } catch (ignored: Throwable) {
        }
        try {
            val decor = window.decorView ?: return
            // OR the layout flags in — never overwrite what Instagram set
            // (light/dark icon flags stay exactly as it chose them, so the
            // status icons keep the colour Instagram intended).
            val flags = decor.systemUiVisibility or
                View.SYSTEM_UI_FLAG_LAYOUT_STABLE or
                View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or
                View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
            if (decor.systemUiVisibility != flags) decor.systemUiVisibility = flags
            flaggedDecors.add(decor)
        } catch (ignored: Throwable) {
        }
        try {
            // 1.19.1: the decor's navigationBarBackground view paints
            // the bottom strip light even with the window colour
            // transparent — recolor the view itself when it is
            // opaque-light (Reels, where it is transparent, is left
            // untouched by the guard inside).
            blackenNavBarBackground(a)
        } catch (ignored: Throwable) {
        }
        try {
            attachTopScrim(a)
        } catch (ignored: Throwable) {
        }
    }

    /**
     * 1.19.1: recolor the decor's navigation-bar background view.
     *
     * The view (android:id/navigationBarBackground, a direct child of
     * the decor) is the framework's own nav-bar background: on the
     * 1.19 probe it sits at exactly [0,1184][720,1280] and paints the
     * strip light, even though window.navigationBarColor is set to
     * TRANSPARENT on every sweep — the window attribute does not reach
     * it on this build. The same view is transparent on the Reels
     * screen (video fills to the bottom), so this only ever writes
     * when the current background is an OPAQUE LIGHT colour: alpha
     * >= 200 and luminance > 128. Transparent (Reels), semi-transparent
     * and already-dark backgrounds are left alone, and a view once
     * blackened no longer matches the predicate — a settled state is
     * a no-op, so this can never loop or flicker. A missing view, an
     * invisible view, no background, or a non-colour background are
     * all skipped (the last two logged once per instance, so the
     * probe log shows exactly which case held).
     */
    private fun blackenNavBarBackground(a: Activity) {
        try {
            val decor = a.window?.decorView as? ViewGroup ?: return
            val navBg = decor.findViewById<View>(android.R.id.navigationBarBackground)
                ?: return
            if (navBg.visibility != View.VISIBLE) return
            val drawable = navBg.background
            if (drawable == null) {
                if (navBarBgLogged.add(navBg)) {
                    RdxLog.d("fullscreen navBarBackground has no background drawable")
                }
                return
            }
            val bg = drawable as? ColorDrawable
            if (bg == null) {
                if (navBarBgLogged.add(navBg)) {
                    RdxLog.d(
                        "fullscreen navBarBackground unexpected background: " +
                            drawable.javaClass.simpleName
                    )
                }
                return
            }
            val c = bg.color
            if (Color.alpha(c) >= 200 &&
                (Color.red(c) * 299 + Color.green(c) * 587 +
                    Color.blue(c) * 114) / 1000 > 128
            ) {
                navBg.setBackgroundColor(Color.BLACK)
                RdxLog.d(
                    "fullscreen navBarBackground #" +
                        Integer.toHexString(c) + " -> black"
                )
            }
        } catch (ignored: Throwable) {
        }
    }

    /**
     * The very light top veil: a non-touchable gradient laid over the
     * content at the top of the decor (drawn above the feed/header, below
     * the system status icons, which live in their own window). 1.19:
     * five stops instead of three, so the fade is smoother, and it ends
     * just below the status icons (status-bar height + 12dp) — only
     * under the icons, nowhere else. Black ~19% at the very top fading
     * to transparent — barely there, only enough to keep the status
     * icons readable over a bright photo.
     * This is a scrim, NOT a blur — see the class doc.
     */
    private fun attachTopScrim(a: Activity) {
        val decor = a.window?.decorView as? ViewGroup ?: return
        val existing = decor.getTag(TAG_TOP_SCRIM) as? View
        if (existing != null && existing.parent === decor) return
        val scrimHeight = statusBarHeight(a) + dp(a, 12)
        val scrim = View(a)
        val gradient = GradientDrawable(
            GradientDrawable.Orientation.TOP_BOTTOM,
            intArrayOf(
                Color.argb(48, 0, 0, 0), // ~19% black at the very top
                Color.argb(30, 0, 0, 0), // ~12%
                Color.argb(16, 0, 0, 0), // ~6%
                Color.argb(6, 0, 0, 0), // ~2%
                Color.argb(0, 0, 0, 0) // transparent at the bottom edge
            )
        )
        scrim.background = gradient
        scrim.isClickable = false
        scrim.isFocusable = false
        scrim.importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
        val lp = FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, scrimHeight, Gravity.TOP
        )
        // The decor is a FrameLayout; a plain ViewGroup parent still lays
        // a MATCH_PARENT-width / fixed-height child out at the top.
        scrim.layoutParams = lp
        decor.addView(scrim)
        decor.setTag(TAG_TOP_SCRIM, scrim)
    }

    private fun statusBarHeight(a: Activity): Int {
        try {
            val res = a.resources
            val id = res.getIdentifier("status_bar_height", "dimen", "android")
            if (id != 0) {
                val px = res.getDimensionPixelSize(id)
                if (px > 0) return px
            }
        } catch (ignored: Throwable) {
        }
        return dp(a, 24)
    }

    private fun dp(a: Activity, dp: Int): Int {
        return Math.round(dp * a.resources.displayMetrics.density)
    }

    // -- geometry: move the panel to y=0, grow the feed under the capsule ---

    private fun applyGeometry(a: Activity) {
        val root = a.window?.decorView as? ViewGroup ?: return
        val pkg = a.packageName
        try {
            movePanelUp(a, root, pkg)
        } catch (ignored: Throwable) {
        }
        try {
            // 1.19: grow the coordinator to the true bottom FIRST —
            // the panel/wrapper/pager chain can only grow into a
            // parent that is already tall.
            growCoordinator(a, root, pkg)
        } catch (ignored: Throwable) {
        }
        try {
            growFeed(a, root, pkg)
        } catch (ignored: Throwable) {
        }
        try {
            // 1.19: push the top bars below the status icons and
            // shift the content below them by the same amount.
            insetTopChrome(a, root, pkg)
        } catch (ignored: Throwable) {
        }
        try {
            // 1.19: lift the reels caption + action rail above the
            // capsule (measured live against the bar's real top).
            raiseReelChrome(a, root, pkg)
        } catch (ignored: Throwable) {
        }
        try {
            // The 1px divider ABOVE the bar is a sibling of the bar, not a
            // child — TabBarHook.hideDivider never sees it. With the feed
            // behind the capsule it would read as a stray line across the
            // feed, so hide it.
            val shadow = findByName(root, a, "tab_bar_shadow", pkg)
            if (shadow != null) hideView(shadow)
        } catch (ignored: Throwable) {
        }
        try {
            // Instagram's own floating gradient strip behind the bar
            // (X/00YD.A0E): a fade over the feed. The spec wants the area
            // behind the capsule FULLY transparent, so hide it too.
            val gradient = findByName(root, a, "floating_tab_bar_nav_bar_gradient", pkg)
            if (gradient != null) hideView(gradient)
        } catch (ignored: Throwable) {
        }
    }

    /**
     * Move the main panel itself to y=0. The panel is the first view in
     * the chain that starts at y=48 (its parent starts at y=0), so the
     * 48 px — exactly the status-bar height — is applied AT the panel:
     * a top margin set by Instagram's code, top padding on an ancestor
     * (fitsSystemWindows), or a CoordinatorLayout Behavior. All three
     * are undone here. Clearing the wrapper's top padding (the 1.13
     * approach) is NOT the fix and is only kept below as a harmless
     * no-op when already 0 — padding never moves a view's top edge.
     * The panel keeps its full height (MATCH_PARENT in its 1184-tall
     * parent), so the bottom-anchored tab bar does not move.
     */
    private fun movePanelUp(a: Activity, root: ViewGroup, pkg: String) {
        val panel = findByName(root, a, "layout_container_main_panel", pkg) ?: return
        // 1. The panel's own top margin — the most likely seat.
        clearTopMargin(panel)
        // 2. A CoordinatorLayout Behavior seats the child in onLayoutChild
        //    and ignores the margin; remove it once, reflectively (no
        //    compile-time dependency on coordinatorlayout).
        removeBehavior(panel)
        // 3. The inset can equally arrive as top padding on an ancestor:
        //    walk from the panel's parent up to the decor and clear any
        //    top padding found (saved + logged per view).
        val decor = a.window?.decorView
        var ancestor = panel.parent as? ViewGroup
        while (ancestor != null && ancestor !== decor) {
            try {
                if (ancestor.paddingTop > 0) {
                    savePadding(ancestor)
                    val before = ancestor.paddingTop
                    ancestor.setPadding(
                        ancestor.paddingLeft, 0,
                        ancestor.paddingRight, ancestor.paddingBottom
                    )
                    RdxLog.d(
                        "fullscreen ancestor " + ancestor.javaClass.simpleName +
                            " paddingTop " + before + " -> 0"
                    )
                }
            } catch (ignored: Throwable) {
            }
            ancestor = ancestor.parent as? ViewGroup
        }
        // 4. Stop the inset being re-applied on the next dispatch, and do
        //    the same margin clear on the wrapper (it fills the panel, so
        //    its own top margin would hold the content down even with the
        //    panel at y=0).
        try {
            if (fitsCleared.add(panel)) panel.fitsSystemWindows = false
        } catch (ignored: Throwable) {
        }
        try {
            val wrapper = findByName(root, a, "layout_container_main_wrapper", pkg)
            if (wrapper != null) {
                clearTopMargin(wrapper)
                if (fitsCleared.add(wrapper)) wrapper.fitsSystemWindows = false
                clearTopPadding(wrapper)
            }
        } catch (ignored: Throwable) {
        }
        // 5. Confirmation, logged once: the panel's layout top is 0 only
        //    after a layout pass has run with the margin gone.
        try {
            if (panel.top == 0 && panelTopConfirmed.add(panel)) {
                RdxLog.d("fullscreen panel top=0 confirmed")
            }
        } catch (ignored: Throwable) {
        }
    }

    /**
     * Grow the feed chain so content scrolls UNDER the capsule instead of
     * stopping 96 px above it. The chain is pager -> inner RecyclerView
     * -> layout_container_swipeable -> sticky_header_list ->
     * refreshable_container -> feed RecyclerView (android:id/list); a
     * short link anywhere caps the feed list. Each link is grown to its
     * parent (bottom margin cleared, height MATCH_PARENT, children
     * allowed to draw into the padding area, bottom padding cleared).
     * The feed list keeps its TOP padding: it is the header height, and
     * the sticky header floats over the list — clearing it would slide
     * the stories tray under the header at rest.
     */
    private fun growFeed(a: Activity, root: ViewGroup, pkg: String) {
        val wrapper = findByName(root, a, "layout_container_main_wrapper", pkg)
        val pager = findByName(root, a, "swipeable_tab_view_pager", pkg) ?: return
        if (wrapper != null) growViewToParent(pager, wrapper)
        try {
            val inner = findByName(
                root, a, "swipeable_nav_view_pager_inner_recycler_view", pkg
            )
            if (inner != null) growViewToParent(inner, pager)
        } catch (ignored: Throwable) {
        }
        for (name in arrayOf(
            "layout_container_swipeable", "sticky_header_list", "refreshable_container"
        )) {
            try {
                val v = findByName(root, a, name, pkg) ?: continue
                val parent = v.parent as? ViewGroup ?: continue
                growViewToParent(v, parent)
            } catch (ignored: Throwable) {
            }
        }
        try {
            val list = findByNameInPackage(root, a, "list", "android")
            if (list != null) {
                val parent = list.parent as? ViewGroup
                if (parent != null) growViewToParent(list, parent)
            }
        } catch (ignored: Throwable) {
        }
        attachPagerListener(pager)
        // Confirmation, logged once.
        try {
            if (wrapper != null && pager.height > 0 && pager.height >= wrapper.height &&
                pagerHeightConfirmed.add(pager)
            ) {
                RdxLog.d(
                    "fullscreen pager full height confirmed: " + pager.height +
                        " / wrapper " + wrapper.height
                )
            }
        } catch (ignored: Throwable) {
        }
    }

    /**
     * 1.19: grow the coordinator to the true bottom. The coordinator
     * (layout_container_center_right_coordinator_layout) is 1184 tall
     * on a 1280 screen — the bottom 96 px is the system nav-bar
     * inset, and every view below it (panel, wrapper, pager, feed)
     * is capped by it. The bottom inset is recorded BEFORE growing
     * (sticky — after growth the difference reads 0) so TabBarHook
     * can hold the capsule where it is.
     */
    private fun growCoordinator(a: Activity, root: ViewGroup, pkg: String) {
        val coordinator = findByName(
            root, a, "layout_container_center_right_coordinator_layout", pkg
        ) ?: return
        val parent = coordinator.parent as? ViewGroup ?: return
        try {
            if (bottomInsetPx == 0 && parent.height > coordinator.height &&
                coordinator.height > 0
            ) {
                bottomInsetPx = parent.height - coordinator.height
                RdxLog.d("fullscreen bottom inset measured: " + bottomInsetPx + "px")
            }
        } catch (ignored: Throwable) {
        }
        try {
            if (fitsCleared.add(coordinator)) coordinator.fitsSystemWindows = false
        } catch (ignored: Throwable) {
        }
        growViewToParent(coordinator, parent)
    }

    /**
     * 1.19: push every top bar below the status icons and shift the
     * content below it by the same amount. The media itself stays
     * full-bleed from y=0 — only the chrome moves.
     *
     * A "top bar" is found structurally (not by name, so future
     * screens get the same treatment): window-top == 0, height
     * 40–100dp, width >= 90% of the screen, not an ancestor of the
     * feed list (never descend into android:id/list — the gap spacer,
     * the stories tray and the posts all sit at the top too but are
     * content, not chrome), and not the panel/wrapper/pager itself
     * (their heights rule them out). The outermost match wins: once
     * a bar is found its children are not walked (they move with it).
     * Known bars are maintained by identity (their window top is the
     * shift once applied, so the discovery walk would no longer see
     * them at y=0).
     */
    private fun insetTopChrome(a: Activity, root: ViewGroup, pkg: String) {
        // The panel is a ViewGroup (a layout container); the safe
        // cast keeps the compiler honest — findByName returns View.
        val panel = findByName(root, a, "layout_container_main_panel", pkg) as? ViewGroup
            ?: return
        val shift = statusBarHeight(a)
        if (shift <= 0) return
        val screenW = a.resources.displayMetrics.widthPixels
        val list = findByNameInPackage(root, a, "list", "android")
        // 1. Maintain the chrome already shifted (by identity).
        try {
            val entries = ArrayList(chromeShifts.entries)
            for ((view, state) in entries) {
                if (!view.isAttachedToWindow) {
                    chromeShifts.remove(view)
                    continue
                }
                convergeChrome(view, state)
            }
        } catch (ignored: Throwable) {
        }
        // 2. Discover new top bars (still at y=0).
        val bars = ArrayList<View>()
        try {
            collectTopBars(a, panel, list, screenW, bars)
        } catch (ignored: Throwable) {
        }
        for (bar in bars) {
            if (chromeShifts.containsKey(bar)) continue
            discoverChrome(bar, shift, isHeader = true)
        }
        // 3. For every known header, find the content below it (or
        // the feed list) and shift that too.
        try {
            val headers = ArrayList<View>()
            for ((view, state) in chromeShifts) {
                if (state.isHeader) headers.add(view)
            }
            for (header in headers) {
                val headerBottom = header.height // original bottom (top was 0)
                if (headerBottom <= 0) continue
                val content = findContentBelow(
                    a, panel, list, screenW, header, headerBottom
                )
                if (content != null) {
                    if (!chromeShifts.containsKey(content)) {
                        discoverChrome(content, headerBottom + shift, isHeader = false)
                    }
                } else if (isFeedHeader(header, a, pkg)) {
                    shiftFeedListTop(a, root, pkg, shift)
                }
            }
        } catch (ignored: Throwable) {
        }
    }

    /** Record a newly found chrome view and apply its first shift. */
    private fun discoverChrome(v: View, targetTop: Int, isHeader: Boolean) {
        try {
            val lp = v.layoutParams as? ViewGroup.MarginLayoutParams
            val origMargin = lp?.topMargin ?: 0
            val origTop = windowTop(v)
            val state = ChromeShift(origMargin, 0, targetTop, origTop, isHeader)
            chromeShifts[v] = state
            if (lp != null) {
                val want = origMargin + (targetTop - origTop)
                if (lp.topMargin != want) {
                    lp.topMargin = want
                    v.layoutParams = lp
                }
                RdxLog.d(
                    "chrome " + describe(v) + " topMargin " + origMargin +
                        " -> " + want + " (targetTop " + targetTop + ")"
                )
            } else {
                // No margin params on this parent: straight to
                // translation (the only mechanism left).
                state.mode = 1
                v.translationY = (targetTop - origTop).toFloat()
                RdxLog.d(
                    "chrome " + describe(v) +
                        " no MarginLayoutParams; translationY " + v.translationY
                )
            }
        } catch (ignored: Throwable) {
        }
    }

    /** Keep one shifted chrome view on its target top. */
    private fun convergeChrome(v: View, state: ChromeShift) {
        try {
            state.sweepsSeen++
            if (state.mode == 0) {
                // Layout top, not window top: Instagram's own
                // translationY (hide-on-scroll) must not be mistaken
                // for a margin that did not work.
                val layoutTop = (windowTop(v) - v.translationY).toInt()
                if (Math.abs(layoutTop - state.targetTop) <= 1) return
                if (state.sweepsSeen >= 2) {
                    // One full layout cycle has run with the margin
                    // set and the view still has not moved: this
                    // parent does not honour top margins. Revert it
                    // and hold the view with translation instead.
                    val lp = v.layoutParams as? ViewGroup.MarginLayoutParams
                    if (lp != null && lp.topMargin != state.origMargin) {
                        lp.topMargin = state.origMargin
                        v.layoutParams = lp
                    }
                    state.mode = 1
                    v.translationY = (state.targetTop - layoutTop).toFloat()
                    RdxLog.d(
                        "chrome " + describe(v) +
                            " top margin ignored; using translationY " +
                            v.translationY
                    )
                } else {
                    // Re-assert the margin (Instagram may have reset
                    // it); the next sweep decides whether it sticks.
                    val lp = v.layoutParams as? ViewGroup.MarginLayoutParams
                    if (lp != null) {
                        val want = state.origMargin +
                            (state.targetTop - state.origLayoutTop)
                        if (lp.topMargin != want) {
                            lp.topMargin = want
                            v.layoutParams = lp
                        }
                    }
                }
            } else {
                val top = windowTop(v)
                val diff = state.targetTop - top
                if (Math.abs(diff) > 1) {
                    v.translationY = v.translationY + diff.toFloat()
                }
            }
        } catch (ignored: Throwable) {
        }
    }

    /** Pre-order walk of the panel subtree for unshifted top bars. */
    private fun collectTopBars(
        a: Activity, panel: ViewGroup, list: View?, screenW: Int, out: MutableList<View>
    ) {
        val minH = dp(a, 40)
        val maxH = dp(a, 100)
        val minW = (screenW * 0.9f).toInt()
        val stack = ArrayDeque<View>()
        stack.add(panel)
        while (stack.isNotEmpty()) {
            val v = stack.removeLast()
            if (v !== panel) {
                if (v.isAttachedToWindow) {
                    val top = windowTop(v)
                    val h = v.height
                    val w = v.width
                    if (top == 0 && h in minH..maxH && w >= minW) {
                        out.add(v)
                        continue // children move with the bar; do not descend
                    }
                }
            }
            val vg = v as? ViewGroup ?: continue
            if (list != null && v === list) continue // never into the feed list
            for (i in vg.childCount - 1 downTo 0) {
                val child = vg.getChildAt(i) ?: continue
                stack.add(child)
            }
        }
    }

    /**
     * The outermost view below a header: window-top == the header's
     * original bottom (±2 px), taller than 100dp, >= 90% of the screen
     * wide, not inside the header and not inside the feed list.
     * Pre-order, so the first match is the outermost (profile
     * tab_appbar, direct list_container). Returns null when the
     * header floats over background content (reels: the video).
     */
    private fun findContentBelow(
        a: Activity, panel: ViewGroup, list: View?, screenW: Int,
        header: View, headerBottom: Int
    ): View? {
        val minH = dp(a, 100)
        val minW = (screenW * 0.9f).toInt()
        val stack = ArrayDeque<View>()
        stack.add(panel)
        while (stack.isNotEmpty()) {
            val v = stack.removeLast()
            if (v !== panel && v !== header) {
                if (v.isAttachedToWindow) {
                    val top = windowTop(v)
                    val h = v.height
                    val w = v.width
                    if (Math.abs(top - headerBottom) <= 2 && h > minH && w >= minW) {
                        return v
                    }
                }
            }
            val vg = v as? ViewGroup ?: continue
            if (v === header) continue
            if (list != null && v === list) continue
            for (i in vg.childCount - 1 downTo 0) {
                val child = vg.getChildAt(i) ?: continue
                stack.add(child)
            }
        }
        return null
    }

    /** The feed header: its list is shifted by padding, not by margin. */
    private fun isFeedHeader(bar: View, a: Activity, pkg: String): Boolean {
        return try {
            val res = a.resources
            val id1 = res.getIdentifier("action_bar_LinearLayout", "id", pkg)
            val id2 = res.getIdentifier("main_feed_action_bar", "id", pkg)
            (id1 != 0 && bar.id == id1) || (id2 != 0 && bar.id == id2)
        } catch (ignored: Throwable) {
            false
        }
    }

    /**
     * Feed list top padding += the status-bar height, so the stories
     * tray and the posts start below the shifted header. Padding —
     * not a margin on the list container — so scrolled content still
     * draws under the header and the status bar (clipToPadding is
     * already false on this chain).
     */
    private fun shiftFeedListTop(a: Activity, root: ViewGroup, pkg: String, shift: Int) {
        try {
            val list = findByNameInPackage(root, a, "list", "android") ?: return
            val orig = savedListTopPadding[list] ?: list.paddingTop.also {
                savedListTopPadding[list] = it
            }
            val want = orig + shift
            if (list.paddingTop != want) {
                list.setPadding(
                    list.paddingLeft, want, list.paddingRight, list.paddingBottom
                )
                RdxLog.d("chrome feed list paddingTop " + orig + " -> " + want)
            }
        } catch (ignored: Throwable) {
        }
    }

    /**
     * 1.19: lift the reels caption and action rail above the capsule.
     * clips_media_info_component and clips_ufi_component both end at
     * y=1102 on the probe — 30 px INSIDE the capsule zone (capsule
     * top 1072). Their bottoms are raised to (bar top − 8dp), measured
     * live against the bar's real position so the fix holds on any
     * density. translationY: it works regardless of how the parent
     * positions the view, and it is re-applied whenever Instagram's
     * entrance animator resets it. Convergent both ways (a shorter
     * caption eases back down, never below its base position).
     */
    private fun raiseReelChrome(a: Activity, root: ViewGroup, pkg: String) {
        try {
            val bar = findBarByTab(root, a) ?: return
            val barLoc = IntArray(2)
            bar.getLocationInWindow(barLoc)
            val barTop = barLoc[1]
            if (barTop <= 0) return
            val desiredBottom = barTop - dp(a, 8)
            for (name in arrayOf("clips_media_info_component", "clips_ufi_component")) {
                val v = findByName(root, a, name, pkg) ?: continue
                if (!v.isAttachedToWindow || v.height <= 0) continue
                val loc = IntArray(2)
                v.getLocationInWindow(loc)
                val bottom = loc[1] + v.height
                val diff = desiredBottom - bottom
                if (diff < -1) {
                    v.translationY = v.translationY + diff.toFloat()
                    RdxLog.d(
                        "fullscreen reel chrome " + name + " lifted by " +
                            (-diff) + "px (bottom " + bottom + " -> " +
                            desiredBottom + ")"
                    )
                } else if (diff > 8 && v.translationY < 0f) {
                    // Shorter caption than the one that was lifted:
                    // ease back down, never below the base position.
                    val eased = Math.min(0f, v.translationY + diff.toFloat())
                    if (eased != v.translationY) v.translationY = eased
                }
            }
        } catch (ignored: Throwable) {
        }
    }

    /** The tab bar: parent of feed_tab (same lookup as TabBarHook). */
    private fun findBarByTab(root: ViewGroup, a: Activity): ViewGroup? {
        return try {
            val id = a.resources.getIdentifier("feed_tab", "id", a.packageName)
            if (id == 0) return null
            val tab = root.findViewById<View>(id) ?: return null
            tab.parent as? ViewGroup
        } catch (ignored: Throwable) {
            null
        }
    }

    /** Window top of a view (decor-relative y of its top edge). */
    private fun windowTop(v: View): Int {
        return try {
            val loc = IntArray(2)
            v.getLocationInWindow(loc)
            loc[1]
        } catch (ignored: Throwable) {
            -1
        }
    }

    /**
     * Grow one feed-chain view to fill its parent. Only ever writes a
     * value that actually differs, so a settled layout is a no-op.
     * Escalation: MATCH_PARENT is the clean fix, but if the view still
     * measures shorter than its parent after a layout pass with
     * MATCH_PARENT set (Instagram reset the height, or the parent caps
     * it), pin an explicit fixed height equal to the parent's measured
     * height. If even that does not stick, the parent lays the view out
     * directly and nothing parametric is left — that is logged once as
     * evidence for the probe, not retried forever.
     */
    private fun growViewToParent(v: View, parent: View) {
        try {
            val lp = v.layoutParams ?: return
            val parentH = parent.height
            var changed = false
            if (lp is ViewGroup.MarginLayoutParams && lp.bottomMargin > 0) {
                saveMargins(v, lp)
                val before = lp.bottomMargin
                lp.bottomMargin = 0
                changed = true
                RdxLog.d("fullscreen " + describe(v) + " bottomMargin " + before + " -> 0")
            }
            if (lp.height != ViewGroup.LayoutParams.MATCH_PARENT && lp.height != parentH) {
                // Instagram reset the height to a short fixed value.
                if (!savedHeights.containsKey(v)) savedHeights[v] = lp.height
                val before = lp.height
                lp.height = ViewGroup.LayoutParams.MATCH_PARENT
                changed = true
                RdxLog.d("fullscreen " + describe(v) + " height " + before + " -> MATCH_PARENT")
            } else if (lp.height == ViewGroup.LayoutParams.MATCH_PARENT &&
                v.height > 0 && parentH > v.height
            ) {
                // MATCH_PARENT is set yet the view still measures short
                // after a layout pass — escalate to an explicit fixed
                // height equal to the parent's measured height.
                if (!savedHeights.containsKey(v)) savedHeights[v] = lp.height
                lp.height = parentH
                changed = true
                RdxLog.d(
                    "fullscreen " + describe(v) + " height escalated to fixed " +
                        parentH + "px (measured " + v.height + " / parent " + parentH + ")"
                )
            } else if (lp.height == parentH && parentH > 0 &&
                v.height > 0 && parentH > v.height &&
                escalationCapped.add(v)
            ) {
                // Even the fixed height does not stick: the parent lays
                // this view out directly. Log once as probe evidence.
                RdxLog.d(
                    "fullscreen " + describe(v) + " height fixed " + parentH +
                        "px still measures " + v.height + " — parent caps it"
                )
            }
            if (changed) v.layoutParams = lp
        } catch (ignored: Throwable) {
        }
        try {
            val vg = v as? ViewGroup
            if (vg != null && vg.clipToPadding) vg.clipToPadding = false
        } catch (ignored: Throwable) {
        }
        try {
            clearBottomPadding(v)
        } catch (ignored: Throwable) {
        }
    }

    /**
     * Re-assert the pager's height on its OWN layout changes. The
     * debounced sweep already re-applies every ~400 ms after a global
     * layout, but Instagram can reset the height without a global
     * layout pass (a direct layout call); this listener catches that
     * immediately. Guarded on the layout-params VALUE, not the
     * measured height, so a settled layout is a no-op and this can
     * never loop: once the height is MATCH_PARENT (or the escalated
     * fixed parent height), nothing more is written.
     */
    private fun attachPagerListener(pager: View) {
        try {
            if (!pagerListenerAttached.add(pager)) return
            pager.addOnLayoutChangeListener(object : View.OnLayoutChangeListener {
                override fun onLayoutChange(
                    v: View, left: Int, top: Int, right: Int, bottom: Int,
                    oldLeft: Int, oldTop: Int, oldRight: Int, oldBottom: Int
                ) {
                    try {
                        val parent = v.parent as? ViewGroup ?: return
                        val parentH = parent.height
                        if (parentH <= 0) return
                        val lp = v.layoutParams ?: return
                        if (lp.height != ViewGroup.LayoutParams.MATCH_PARENT &&
                            lp.height != parentH
                        ) {
                            val before = lp.height
                            lp.height = ViewGroup.LayoutParams.MATCH_PARENT
                            v.layoutParams = lp
                            RdxLog.d(
                                "fullscreen " + describe(v) +
                                    " height reset by Instagram, re-asserted MATCH_PARENT (was " +
                                    before + ")"
                            )
                        }
                    } catch (ignored: Throwable) {
                    }
                }
            })
        } catch (ignored: Throwable) {
        }
    }

    /**
     * Remove a CoordinatorLayout Behavior seating this view, if it has
     * one. Reflective: the theme module has no compile-time dependency
     * on coordinatorlayout, and the class may not exist on some builds.
     * Checked once per view instance.
     */
    private fun removeBehavior(v: View) {
        try {
            val lp = v.layoutParams ?: return
            val lpClass = lp.javaClass
            if (lpClass.name !=
                "androidx.coordinatorlayout.widget.CoordinatorLayout\$LayoutParams"
            ) return
            if (!behaviorChecked.add(v)) return
            val getBehavior = try {
                lpClass.getMethod("getBehavior")
            } catch (e: NoSuchMethodException) {
                return
            }
            val behavior = getBehavior.invoke(lp) ?: return
            val behaviorClass = try {
                Class.forName(
                    "androidx.coordinatorlayout.widget.CoordinatorLayout\$Behavior"
                )
            } catch (e: ClassNotFoundException) {
                return
            }
            val setBehavior = try {
                lpClass.getMethod("setBehavior", behaviorClass)
            } catch (e: NoSuchMethodException) {
                return
            }
            setBehavior.invoke(lp, null)
            v.layoutParams = lp
            RdxLog.d(
                "fullscreen " + describe(v) +
                    " CoordinatorLayout behavior removed: " + behavior.javaClass.name
            )
        } catch (ignored: Throwable) {
        }
    }

    private fun findByName(root: ViewGroup, a: Activity, name: String, pkg: String): View? {
        return findByNameInPackage(root, a, name, pkg)
    }

    private fun findByNameInPackage(
        root: ViewGroup, a: Activity, name: String, pkg: String
    ): View? {
        try {
            val id = a.resources.getIdentifier(name, "id", pkg)
            if (id == 0) return null
            return root.findViewById<View>(id)
        } catch (ignored: Throwable) {
            return null
        }
    }

    private fun describe(v: View): String {
        return try {
            val id = v.id
            if (id != View.NO_ID) v.resources.getResourceEntryName(id)
            else v.javaClass.simpleName
        } catch (ignored: Throwable) {
            try {
                v.javaClass.simpleName
            } catch (ignored2: Throwable) {
                "view"
            }
        }
    }

    private fun savePadding(v: View) {
        if (!savedPaddings.containsKey(v)) {
            savedPaddings[v] = intArrayOf(
                v.paddingLeft, v.paddingTop, v.paddingRight, v.paddingBottom
            )
        }
    }

    private fun saveMargins(v: View, lp: ViewGroup.MarginLayoutParams) {
        if (!savedMargins.containsKey(v)) {
            savedMargins[v] = intArrayOf(
                lp.leftMargin, lp.topMargin, lp.rightMargin, lp.bottomMargin
            )
        }
    }

    private fun clearTopMargin(v: View) {
        try {
            val lp = v.layoutParams as? ViewGroup.MarginLayoutParams ?: return
            if (lp.topMargin <= 0) return
            saveMargins(v, lp)
            val before = lp.topMargin
            lp.topMargin = 0
            v.layoutParams = lp
            RdxLog.d("fullscreen " + describe(v) + " topMargin " + before + " -> 0")
        } catch (ignored: Throwable) {
        }
    }

    private fun clearTopPadding(v: View) {
        if (v.paddingTop <= 0) return
        savePadding(v)
        v.setPadding(v.paddingLeft, 0, v.paddingRight, v.paddingBottom)
    }

    private fun clearBottomPadding(v: View) {
        if (v.paddingBottom <= 0) return
        savePadding(v)
        v.setPadding(v.paddingLeft, v.paddingTop, v.paddingRight, 0)
    }

    private fun hideView(v: View) {
        if (v.visibility == View.GONE) return
        if (!savedVisibility.containsKey(v)) savedVisibility[v] = v.visibility
        v.visibility = View.GONE
    }
}
