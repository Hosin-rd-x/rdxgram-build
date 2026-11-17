package ir.rdx.gram.theme

import android.app.Activity
import android.graphics.Color
import android.graphics.drawable.ColorDrawable
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.WindowInsets
import android.view.WindowManager
import android.widget.FrameLayout
import java.util.Collections
import java.util.WeakHashMap
import java.lang.ref.WeakReference

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
 * 1.19.2 (on top of 1.19.1) — the tab-switch mess on Hossein's phone:
 *  - switching tabs messes up the full-screen state and the icons,
 *    sometimes STUCK (feed pushed ~156dp down under a black band,
 *    wordmark gone, capsule gone; Reels fine 10 min later). Root
 *    cause: Instagram re-adds/re-orders the wrapper's children on tab
 *    switches (1.19.1 probe dump ui_step_tab04after proves it), and
 *    every geometry re-assert was gated on cached/one-shot state —
 *    the pre-draw guard checked only the bar BACKGROUND, movePanelUp
 *    never cleared the panel's OWN paddingTop, bottomInsetPx was
 *    measured once and sticky, growViewToParent pinned a fixed height
 *    from one transient measurement, convergeChrome ACCUMULATED
 *    translationY (+= diff) unboundedly, and shiftFeedListTop trusted
 *    a first-sight orig forever. This version re-asserts MEASURED
 *    geometry everywhere: a geometry guard on pre-draw (bar margins /
 *    elevation / draw order), a synchronous panel assert on every
 *    layout pass, a two-sweep-stable bottom inset (growth waits for
 *    it), a stable-parent-height escalation, absolute (never
 *    accumulated) translationY with a clamp and a 5-sweep drop +
 *    re-discover, a two-sweep-stable list-padding re-derivation, and
 *    layout_container_main grown too. The driver now asserts the
 *    settled geometry after every tab switch (GEOMETRY_BROKEN fails
 *    the probe) — a clean probe must mean the bug is gone, not
 *    untested. See work/rebuild-1.19.2/root-cause.md.
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
    // probe). TabBarHook adds it to the bar's bottom margin so the
    // capsule does not slide down when the coordinator grows to the
    // true bottom. Written on the main thread (sweep); read on the
    // same thread.
    // 1.19.3 measurement (see measureBottomInset): PRIMARY source is
    // the decor's own android:id/navigationBarBackground view —
    // untouched by our growth, present at exactly [0,1184][720,1280]
    // on the emulator — inset = decor height − navBg top (window
    // coords); its top edge is also published as navBarTopPx so
    // TabBarHook can clamp the bar above it (backstop). FALLBACK is
    // the coordinator/parent difference, only while the coordinator
    // is laid out and NOT yet grown, and only while the inset is
    // still unknown (the 1.19.1 retry gate).
    // 1.19.3 round 2 (Opus review #1): the gesture handle has no
    // navBg view at all, so the navBg path would conclude inset 0
    // and put the bar on the handle — the gesture case is measured
    // from the system's own WindowInsets instead (see
    // windowInsetsBottomInset). A side nav bar (landscape) likewise
    // contributes nothing to the BOTTOM inset (its width < height,
    // top == 0 — the old displayHeight − top formula would have
    // yielded the whole screen height as an inset).
    // 1.19.2's failure, fixed here: the two-sweep candidate machinery
    // (bottomInsetCandidate / coordinatorGrowAttempted, deleted below)
    // gated ALL measurement on the first sweep, which runs PRE-layout
    // (coordinator.height == 0) — so the unmeasurable branch marked
    // the coordinator "attempted" and the inset stayed 0 forever,
    // while the "already known" branch treated that 0 as a real
    // measurement and grew the coordinator under it. The bar slid
    // 96 px down ([32,1168][688,1264]) and its tab centres landed
    // inside the system nav bar. A 0 that means "never measured"
    // must never be confused with a 0 that means "gesture nav,
    // genuinely no inset" — hence the separate bottomInsetKnown flag.
    @Volatile
    var bottomInsetPx: Int = 0

    // Window Y of the top edge of navigationBarBackground when
    // that view is present and laid out; 0 when there is no system
    // nav bar (gesture nav) or it has not been laid out yet.
    // Window coords (see measureBottomInset) — TabBarHook compares
    // it against the parent's getLocationInWindow, same space.
    // Published for TabBarHook's clamp backstop.
    @Volatile
    var navBarTopPx: Int = 0

    // True once a measurement (from either source) has been accepted.
    // Distinct from bottomInsetPx == 0, which is a legitimate value
    // on gesture navigation.
    private var bottomInsetKnown: Boolean = false

    // True when the current bottomInsetPx came from the nav-bar
    // background (ground truth): it may be re-asserted every sweep.
    // A difference-sourced value is trusted only while the inset is
    // still unknown — it must never overwrite a navBg-sourced one.
    private var bottomInsetTrusted: Boolean = false

    // Which source produced the current bottomInsetPx, for the log
    // line the probe asserts ("navBg" / "windowInsets" /
    // "fallback" / "gesture-0" / "side-nav"). "unknown" while the
    // inset has never been measured.
    private var bottomInsetSource: String = "unknown"

    // Set when the navBg reading and the WindowInsets reading
    // disagree (e.g. "navBg=96 windowInsets=0"); navBg wins (see
    // measureBottomInset). Null when they agree or insets are
    // unavailable. Reset on every measurement.
    private var insetDisagreement: String? = null

    // Consecutive sweeps where navigationBarBackground exists but is
    // not laid out yet (height 0). Two in a row means it will never
    // lay out — the device has no system nav bar (gesture nav) — so
    // the inset is genuinely 0. Reset whenever a laid-out reading
    // arrives. 1.19.3 round 2: counted ONLY when the view HAS been
    // laid out (isLaidOut) with height 0 — a view that simply has
    // not been laid out yet concludes nothing (slow layout).
    private var navBgZeroSweeps: Int = 0

    // Consecutive sweeps where the inset could not be measured at
    // all. After 3, growCoordinator grows anyway (escape hatch) and
    // logs a warning once — the TabBarHook clamp is the backstop.
    // The escape hatch does NOT set bottomInsetKnown: a later navBg
    // reading can still correct the inset.
    private var insetUnknownSweeps: Int = 0
    private var insetEscapeLogged: Boolean = false

    // 1.19.3 round 2: the inset state belongs to ONE decor view.
    // Rotation (or a second activity) brings a new decor; the
    // object-level fields above would otherwise carry the old
    // window's inset (e.g. 96 px portrait) into a landscape window
    // whose bottom inset is 0. measureBottomInset resets all of
    // them when the decor changes (see resetInsetState).
    private var insetDecorRef: WeakReference<View>? = null

    // Coordinators already grown. The coordinator/parent fallback
    // is ONLY valid before growth — after growth the difference
    // reads 0 by construction, and accepting that 0 as known is
    // exactly the 1.19.2 state. Keyed by view identity (weak), so
    // a rebuilt coordinator is measured fresh. This set gates the
    // FALLBACK only, never the navBg primary (which re-measures
    // every sweep).
    private val fallbackBlocked: MutableSet<View> =
        Collections.newSetFromMap(WeakHashMap<View, Boolean>())

    /** Reset all per-decor inset state for a new window. */
    private fun resetInsetState(decor: View) {
        insetDecorRef = WeakReference(decor)
        bottomInsetPx = 0
        navBarTopPx = 0
        bottomInsetKnown = false
        bottomInsetTrusted = false
        bottomInsetSource = "unknown"
        insetDisagreement = null
        navBgZeroSweeps = 0
        insetUnknownSweeps = 0
        insetEscapeLogged = false
    }

    // 1.19.2: cached panel/wrapper for assertPanelGeometry (called on
    // every layout pass — a findByName walk per pass would cost more
    // than the fix it protects). Weak references: a rebuilt panel
    // drops out and is re-found on the next call.
    private var cachedPanelRef: WeakReference<View>? = null
    private var cachedWrapperRef: WeakReference<View>? = null

    // 1.19.2: parent heights seen by the growViewToParent escalation
    // (a fixed height is pinned only from a stable parent height —
    // see growViewToParent), and feed-list padding values that match
    // neither the saved orig nor the wanted value (see
    // shiftFeedListTop).
    private val escalationParentHeight: MutableMap<View, Int> =
        Collections.synchronizedMap(WeakHashMap<View, Int>())
    private val listTopOddValue: MutableMap<View, Int> =
        Collections.synchronizedMap(WeakHashMap<View, Int>())

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
        var sweepsSeen: Int = 0,
        // 1.19.2: consecutive sweeps the view has NOT been on its
        // target top (see convergeChrome). A view that will not
        // converge is dropped after 5, so the next discovery
        // re-derives its shift from the current layout instead of a
        // stale snapshot taken mid-transition.
        var missedSweeps: Int = 0
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

    /**
     * 1.19.2: synchronously re-assert the content panel's geometry.
     * Called from TabBarHook's layout listener on EVERY layout pass —
     * Instagram re-applies the window inset on tab switches, and the
     * debounced sweep (~400 ms later) would let a broken frame paint.
     * Only writes when something actually differs, so a settled layout
     * is a no-op. The panel/wrapper are cached (WeakReference) so the
     * per-pass cost is two pointer reads; the findByName walk runs
     * only when the cached view is gone (rebuilt by Instagram).
     * Panel geometry only ever changes on a layout pass (margin /
     * padding / behavior), never on a bare invalidate — so asserting
     * here, before the draw that follows the layout, means no broken
     * frame can paint. (The bar's BACKGROUND can change without a
     * layout pass, which is why the bar has its own per-frame pre-draw
     * guard in TabBarHook.)
     */
    fun assertPanelGeometry(a: Activity?) {
        if (a == null) return
        try {
            val root = a.window?.decorView as? ViewGroup ?: return
            val pkg = a.packageName
            var panel = cachedPanelRef?.get()
            if (panel == null || !panel.isAttachedToWindow) {
                panel = findByName(root, a, "layout_container_main_panel", pkg)
                cachedPanelRef = if (panel != null) WeakReference(panel) else null
            }
            if (panel != null) {
                clearTopMargin(panel)
                if (panel.paddingTop > 0) {
                    savePadding(panel)
                    panel.setPadding(
                        panel.paddingLeft, 0, panel.paddingRight, panel.paddingBottom
                    )
                }
                try {
                    if (fitsCleared.add(panel)) panel.fitsSystemWindows = false
                } catch (ignored: Throwable) {
                }
                // The inset can equally arrive as top padding on an
                // ancestor (the probe log shows the coordinator
                // ancestor re-applying paddingTop 48 on every tab
                // switch): walk from the panel's parent up to the
                // decor and clear any top padding found. Pointer hops
                // + int reads only — cheap enough for every layout
                // pass. (Same walk as movePanelUp step 3, which keeps
                // running on the sweep as the backstop.)
                try {
                    val decor = a.window?.decorView
                    var ancestor = panel.parent as? ViewGroup
                    while (ancestor != null && ancestor !== decor) {
                        try {
                            if (ancestor.paddingTop > 0) {
                                savePadding(ancestor)
                                ancestor.setPadding(
                                    ancestor.paddingLeft, 0,
                                    ancestor.paddingRight, ancestor.paddingBottom
                                )
                            }
                        } catch (ignored: Throwable) {
                        }
                        ancestor = ancestor.parent as? ViewGroup
                    }
                } catch (ignored: Throwable) {
                }
            }
            var wrapper = cachedWrapperRef?.get()
            if (wrapper == null || !wrapper.isAttachedToWindow) {
                wrapper = findByName(root, a, "layout_container_main_wrapper", pkg)
                cachedWrapperRef = if (wrapper != null) WeakReference(wrapper) else null
            }
            if (wrapper != null) {
                clearTopMargin(wrapper)
                clearTopPadding(wrapper)
                try {
                    if (fitsCleared.add(wrapper)) wrapper.fitsSystemWindows = false
                } catch (ignored: Throwable) {
                }
            }
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
        // 1.19.2 (step 1b): the panel's OWN top padding. An inset
        // dispatch can land the padding on the panel itself; the
        // ancestor walk below starts at the panel's PARENT and never
        // touches it — and the old confirmation (panel.top == 0)
        // passes while a large paddingTop holds the content low.
        try {
            if (panel.paddingTop > 0) {
                savePadding(panel)
                val before = panel.paddingTop
                panel.setPadding(
                    panel.paddingLeft, 0, panel.paddingRight, panel.paddingBottom
                )
                RdxLog.d("fullscreen panel paddingTop " + before + " -> 0")
            }
        } catch (ignored: Throwable) {
        }
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
        // 5. Confirmation, logged once: the panel's layout top is 0
        // AND its top padding is 0. The old check (top == 0 alone)
        // passes while a paddingTop holds the content low (1.19.2) —
        // the content position is the thing that matters. (The exact
        // log string is a probe marker — kept.)
        try {
            if (panel.top == 0 && panel.paddingTop == 0 && panelTopConfirmed.add(panel)) {
                RdxLog.d("fullscreen panel top=0 confirmed (paddingTop 0)")
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
        // 1.19.2: the inner container (layout_container_main) is the
        // link the 1184 cap lives on — the 1.19.1 probe dumps show it
        // at [0,0][720,1184] while the pager is already 1280. Grow it
        // too, into its own parent (the wrapper).
        try {
            val container = findByName(root, a, "layout_container_main", pkg)
            val cParent = container?.parent as? ViewGroup
            if (container != null && cParent != null) {
                growViewToParent(container, cParent)
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
    /**
     * Grow the coordinator to its parent so the feed chain reaches the
     * true bottom — but ONLY once the bottom inset is known.
     *
     * 1.19.3 (fixes the 1.19.2 regression): the inset is measured from
     * ground truth by measureBottomInset — the decor's own
     * navigationBarBackground top (primary), or the coordinator/parent
     * difference while the coordinator is laid out and NOT yet grown
     * (fallback, the 1.19.1 retry gate). Growth waits for a known
     * inset: growing first would make the difference read 0 and the
     * bar would slide under the nav bar (1.19.2: bar [32,1168][688,1264],
     * tab centres inside the system nav bar, every tap after the
     * first hitting SystemUI). Escape hatch: if the inset stays
     * unknown for 3 sweeps (a device where neither source works),
     * grow anyway with a warning — the TabBarHook clamp is the
     * backstop. (The exact "measured" log string is a probe marker —
     * kept.)
     */
    private fun growCoordinator(a: Activity, root: ViewGroup, pkg: String) {
        val coordinator = findByName(
            root, a, "layout_container_center_right_coordinator_layout", pkg
        ) ?: return
        val parent = coordinator.parent as? ViewGroup ?: return
        try {
            val inset = measureBottomInset(a, coordinator, parent)
            if (inset != null) {
                val first = !bottomInsetKnown
                if (bottomInsetTrusted || first) {
                    if (first || inset != bottomInsetPx) {
                        bottomInsetPx = inset
                        bottomInsetKnown = true
                        RdxLog.d(
                            "fullscreen bottom inset measured: " +
                                bottomInsetPx + "px (source=" +
                                bottomInsetSource + ")"
                        )
                        val dis = insetDisagreement
                        if (dis != null) {
                            RdxLog.d(
                                "fullscreen inset sources disagree: " +
                                    dis + " — trusting navBg"
                            )
                        }
                    }
                }
                insetUnknownSweeps = 0
            } else {
                insetUnknownSweeps++
            }
        } catch (ignored: Throwable) {
        }
        try {
            if (fitsCleared.add(coordinator)) coordinator.fitsSystemWindows = false
        } catch (ignored: Throwable) {
        }
        // Growth waits for a known inset (see the doc above). The
        // escape hatch keeps a broken decor lookup from blocking the
        // layout forever.
        if (bottomInsetKnown || insetUnknownSweeps >= 3) {
            if (!bottomInsetKnown && !insetEscapeLogged) {
                insetEscapeLogged = true
                RdxLog.d(
                    "fullscreen growing coordinator without a measured " +
                        "inset (unknown after 3 sweeps)"
                )
            }
            growViewToParent(coordinator, parent)
            // 1.19.3 round 2 (Opus #2): growth ends the fallback
            // for this coordinator — its height difference reads 0
            // from now on, and that 0 must never become the known
            // inset. The navBg primary is unaffected (it re-measures
            // every sweep) and can still correct the inset later;
            // bottomInsetKnown stays false after the escape hatch.
            fallbackBlocked.add(coordinator)
        }
    }

    /**
     * 1.19.3 round 2: the system's own bottom navigation inset,
     * from WindowInsets. This is the ONLY source that sees the
     * gesture handle (navBg is absent on gesture nav, so the navBg
     * path would conclude 0 and put the bar on the handle).
     * API 30+ uses WindowInsets.Type.navigationBars(); below that
     * the deprecated systemWindowInsetBottom. Returns null when
     * insets are not available yet (pre-layout) or the value is
     * insane (> 200 px). Never throws.
     */
    private fun windowInsetsBottomInset(a: Activity): Int? {
        return try {
            val decor = a.window?.decorView ?: return null
            val insets = decor.rootWindowInsets ?: return null
            val bottom = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                insets.getInsets(WindowInsets.Type.navigationBars()).bottom
            } else {
                @Suppress("DEPRECATION")
                insets.systemWindowInsetBottom
            }
            if (bottom in 0..200) bottom else null
        } catch (ignored: Throwable) {
            null
        }
    }

    /**
     * 1.19.3: measure the bottom inset (system navigation bar height)
     * from ground truth. Returns the inset in px, or null when it
     * cannot be known yet. Side effects: publishes navBarTopPx (the
     * window Y of the nav-bar background's top edge; 0 when there is
     * no system nav bar), sets bottomInsetTrusted (true when the
     * current reading came from the nav-bar background or the
     * system insets) and bottomInsetSource (which source produced
     * it, for the log line the probe asserts).
     *
     * PRIMARY — the decor's android:id/navigationBarBackground view:
     * it is a direct child of the decor, untouched by our growth, and
     * present at exactly [0,1184][720,1280] in every emulator dump.
     * inset = decor height − navBg top, both in WINDOW coords (see
     * below). A reading outside 1..200 px is insane — return null
     * (wait) rather than trusting it.
     *   - view absent → gesture nav → inset from WindowInsets
     *     (trusted); 0 only when insets are unavailable too.
     *   - view present but height 0 → not laid out yet → null; a
     *     zero-height streak of >= 2 sweeps WHILE LAID OUT means it
     *     will never lay out (gesture nav) → WindowInsets / 0.
     *   - view present, laid out, but width < height → SIDE nav bar
     *     (landscape): the bottom inset is 0 (WindowInsets if it
     *     has a value), re-measured every sweep.
     * The inset is computed from WINDOW geometry, not
     * displayMetrics.heightPixels: on some API levels / OEM ROMs the
     * display metrics exclude the nav bar, which would compute 0
     * and re-create 1.19.2; the decor's own height cannot lie about
     * its own window. On the emulator both give 1280 − 1184 = 96
     * (verified against the real 1.19.2 dumps).
     * WindowInsets is the cross-check on the navBg path and the
     * source on the gesture/side paths — but NOT the primary over a
     * laid-out navBg: navBg is dump-verifiable ground truth, while
     * the insets' behaviour on Redroid + this app's edge-to-edge
     * flags is unverified until the probe runs, and a wrong trusted
     * 0 from insets would re-create 1.19.2. A disagreement is
     * logged where the value is accepted.
     * FALLBACK — the coordinator/parent difference, only while the
     * coordinator is laid out and NOT yet grown (parent.height >
     * coordinator.height; after growth they are equal, so this can
     * never return a post-growth 0). It never overwrites a
     * navBg-sourced value — that decision is made by the caller via
     * bottomInsetTrusted. A fallback 0 is rejected outright.
     * If the decor lookup itself fails, the fallback is still tried:
     * a missing decor must not block measurement.
     */
    private fun measureBottomInset(
        a: Activity, coordinator: View, parent: ViewGroup
    ): Int? {
        // 1.19.3 round 2: the inset state belongs to one decor view
        // (see resetInsetState) — a new decor re-measures from
        // scratch instead of inheriting the old window's inset.
        try {
            val decor = a.window?.decorView
            if (decor != null && decor !== insetDecorRef?.get()) {
                resetInsetState(decor)
            }
        } catch (ignored: Throwable) {
        }
        insetDisagreement = null
        // PRIMARY: the nav-bar background view (same lookup as
        // blackenNavBarBackground below).
        try {
            val decor = a.window?.decorView as? ViewGroup
            if (decor != null) {
                val navBg = decor.findViewById<View>(
                    android.R.id.navigationBarBackground
                )
                if (navBg != null) {
                    if (navBg.height > 0) {
                        navBgZeroSweeps = 0
                        // Side nav bar (landscape): tall thin view,
                        // top == 0. Contributes nothing to the
                        // BOTTOM inset — 0, re-measured every sweep
                        // (orientation can change at any time).
                        if (navBg.width > 0 && navBg.width < navBg.height) {
                            navBarTopPx = 0
                            val wi = windowInsetsBottomInset(a)
                            bottomInsetTrusted = true
                            bottomInsetSource =
                                if (wi != null) "windowInsets" else "side-nav"
                            return wi ?: 0
                        }
                        val winLoc = IntArray(2)
                        navBg.getLocationInWindow(winLoc)
                        navBarTopPx = winLoc[1]
                        val rootH = navBg.rootView.height
                        if (rootH <= 0) return null
                        val inset = rootH - winLoc[1]
                        if (inset in 1..200) {
                            bottomInsetTrusted = true
                            bottomInsetSource = "navBg"
                            val wi = windowInsetsBottomInset(a)
                            if (wi != null && wi != inset) {
                                insetDisagreement =
                                    "navBg=$inset windowInsets=$wi"
                            }
                            return inset
                        }
                        return null
                    }
                    // Present but not laid out yet: unknown for now.
                    // Count toward the gesture conclusion ONLY when
                    // the view HAS been laid out with height 0 — a
                    // view that simply has not been laid out yet
                    // concludes nothing (slow layout).
                    if (navBg.isLaidOut) {
                        navBgZeroSweeps++
                        if (navBgZeroSweeps >= 2) {
                            navBarTopPx = 0
                            val wi = windowInsetsBottomInset(a)
                            bottomInsetTrusted = true
                            bottomInsetSource =
                                if (wi != null) "windowInsets" else "gesture-0"
                            return wi ?: 0
                        }
                    }
                    return null
                }
                // No navigationBarBackground view at all: gesture
                // nav. The gesture handle inset is non-zero, so the
                // system's own reading is the source — not an
                // assumed 0 (which would put the bar on the handle).
                navBarTopPx = 0
                navBgZeroSweeps = 0
                val wi = windowInsetsBottomInset(a)
                bottomInsetTrusted = true
                bottomInsetSource =
                    if (wi != null) "windowInsets" else "gesture-0"
                return wi ?: 0
            }
        } catch (ignored: Throwable) {
        }
        // FALLBACK: the coordinator difference (1.19.1 retry gate).
        // ONLY valid before growth (see fallbackBlocked): after
        // growth the difference reads 0 by construction. A 0 result
        // is rejected outright — it can never be a measurement.
        return try {
            if (!fallbackBlocked.contains(coordinator) &&
                coordinator.height > 0 && parent.height > coordinator.height) {
                val d = parent.height - coordinator.height
                if (d in 1..200) {
                    bottomInsetTrusted = false
                    bottomInsetSource = "fallback"
                    d
                } else null
            } else null
        } catch (ignored: Throwable) {
            null
        }
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
            // 1.19.2: the effective top — layout top for the margin
            // mode (Instagram's own hide-on-scroll translationY must
            // not be mistaken for a margin that did not work), window
            // top for the translation mode (translationY IS the
            // mechanism there).
            val effectiveTop = if (state.mode == 0) {
                (windowTop(v) - v.translationY).toInt()
            } else {
                windowTop(v)
            }
            if (Math.abs(effectiveTop - state.targetTop) <= 1) {
                state.missedSweeps = 0
                return
            }
            // 1.19.2: a view that will not converge is dropped after
            // 5 sweeps, so the next discovery re-derives origMargin /
            // origTop from the view's CURRENT layout instead of a stale
            // snapshot taken mid-transition. Without this, a wrong
            // shift is re-asserted forever.
            state.missedSweeps++
            if (state.missedSweeps > 5) {
                chromeShifts.remove(v)
                RdxLog.d(
                    "chrome " + describe(v) +
                        " not converging after 5 sweeps; dropping shift (will re-discover)"
                )
                return
            }
            if (state.mode == 0) {
                // Layout top, not window top: Instagram's own
                // translationY (hide-on-scroll) must not be mistaken
                // for a margin that did not work.
                val layoutTop = effectiveTop
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
                // 1.19.2: SET translationY absolutely
                // (targetTop - layoutTop), never accumulate (+= diff).
                // The old accumulation grew unboundedly when the parent
                // re-laid-out the view without moving it — each sweep
                // added the same diff again, pushing the header/tray
                // progressively down (the ~156dp push-down on Hossein's
                // phone). Clamped to one screen height: a chrome view
                // never legitimately translates further than that.
                val layoutTop = (windowTop(v) - v.translationY).toInt()
                var want = (state.targetTop - layoutTop).toFloat()
                val maxShift = v.resources.displayMetrics.heightPixels.toFloat()
                if (want > maxShift) want = maxShift
                if (want < -maxShift) want = -maxShift
                if (v.translationY != want) {
                    v.translationY = want
                    RdxLog.d(
                        "chrome " + describe(v) +
                            " translationY set to " + want +
                            " (targetTop " + state.targetTop + ")"
                    )
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
            val cur = list.paddingTop
            val orig = savedListTopPadding[list]
            if (orig == null) {
                savedListTopPadding[list] = cur
                val want = cur + shift
                list.setPadding(
                    list.paddingLeft, want, list.paddingRight, list.paddingBottom
                )
                RdxLog.d("chrome feed list paddingTop " + cur + " -> " + want)
                return
            }
            val want = orig + shift
            if (cur == want || cur == orig) {
                // Legitimate: our value, or Instagram's own value (not
                // yet shifted). Re-assert ours.
                listTopOddValue.remove(list)
                if (cur != want) {
                    list.setPadding(
                        list.paddingLeft, want, list.paddingRight, list.paddingBottom
                    )
                    RdxLog.d("chrome feed list paddingTop " + orig + " -> " + want)
                }
                return
            }
            // 1.19.2: NEITHER Instagram's value NOR ours — something
            // else changed the padding (transition / rebuild). The old
            // code trusted `orig` forever, so a first sight taken
            // mid-transition locked a wrong want for the life of the
            // list. Re-derive orig from the CURRENT value — but only
            // when it is stable across two consecutive sweeps, so a
            // transient mid-transition value never becomes the new orig.
            val last = listTopOddValue[list]
            if (last != null && last == cur) {
                savedListTopPadding[list] = cur
                listTopOddValue.remove(list)
                val newWant = cur + shift
                list.setPadding(
                    list.paddingLeft, newWant, list.paddingRight, list.paddingBottom
                )
                RdxLog.d(
                    "chrome feed list paddingTop re-derived: orig " + orig +
                        " -> " + cur + " (want " + newWant + ")"
                )
            } else {
                listTopOddValue[list] = cur
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
            // 1.19.2: the view measures full again — drop any stored
            // parent height so a later shrink re-arms the stability
            // wait instead of escalating from a stale reading.
            if (v.height > 0 && parentH > 0 && v.height >= parentH) {
                escalationParentHeight.remove(v)
            }
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
                // 1.19.2: only from a STABLE parent height. During a
                // tab switch the parent's measured height is transient
                // (probe log: the pager oscillating 1136/1232/1280);
                // pinning a fixed height from one transient reading
                // sticks a wrong size. Wait one sweep for the same
                // parent height twice; otherwise stay MATCH_PARENT.
                // (The exact "escalated" log string is a probe marker
                // — kept.)
                val lastH = escalationParentHeight[v]
                if (lastH != null && lastH == parentH) {
                    escalationParentHeight.remove(v)
                    if (!savedHeights.containsKey(v)) savedHeights[v] = lp.height
                    lp.height = parentH
                    changed = true
                    RdxLog.d(
                        "fullscreen " + describe(v) + " height escalated to fixed " +
                            parentH + "px (measured " + v.height + " / parent " + parentH + ")"
                    )
                } else {
                    escalationParentHeight[v] = parentH
                    RdxLog.d(
                        "fullscreen " + describe(v) + " height short (" +
                            v.height + " / parent " + parentH +
                            ") — waiting one sweep for a stable parent height"
                    )
                }
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
