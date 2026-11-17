package ir.rdx.gram.theme

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.content.res.Configuration
import android.graphics.Color
import android.graphics.drawable.Drawable
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.InsetDrawable
import android.os.Handler
import android.os.Looper
import android.view.View
import android.view.ViewGroup
import java.lang.ref.WeakReference
import java.util.Collections
import java.util.WeakHashMap

/**
 * Floating translucent capsule bottom bar (the iOS Instagram look), ported
 * from the earlier GlassTabBarHook (fork Hosin-rd-x/InstaEclipse,
 * branch rdx-glass) into this standalone module.
 *
 * Instagram 451's main navigation is a classic FixedTabBar (a FrameLayout)
 * holding the tab views with stable public resource ids (feed_tab,
 * clips_tab, ...). That parent ViewGroup is the bar, and it is the only
 * thing this hook touches: no bytecode, no colour-resource remap, no
 * navigation order change. The tabs keep their click handling, icons and
 * badges.
 *
 * What a sweep does (debounced):
 *  - finds the bar as the parent of feed_tab, and only trusts it when at
 *    least four of the known tabs are its direct children and it spans most
 *    of the screen width (so a tab strip inside a bottom sheet is never
 *    restyled by mistake);
 *  - paints a translucent capsule on it — semi-transparent fill, a hairline
 *    light edge, corner radius half the bar height — floats it with
 *    side/bottom margins added on top of whatever margins Instagram already
 *    gave it, and drops its elevation to zero;
 *  - puts a smaller translucent pill behind the selected tab's icon (the
 *    iOS highlight), refreshed immediately on every layout pass when the
 *    bar is already known, so it moves with the tap instead of trailing
 *    the 400 ms sweep debounce;
 *  - hides a hairline divider child of the bar, if one is there.
 *
 * Everything is reversible: the bar's original background, margins,
 * elevation, each tab's original background and padding and the divider's
 * visibility are saved on the bar itself (view tags) the first time it is
 * styled, and restored in full when the switch is turned off.
 *
 * Deliberately NOT clipped: the capsule background itself is rounded, and
 * clipping the bar to its outline would cut notification badges and touch
 * ripples at the corners.
 *
 * NO real blur of the content behind the bar. A RenderEffect on the bar
 * itself would blur the bar's own icons, not the backdrop — real backdrop
 * blur needs a blur surface underneath the bar, which a view hook cannot
 * reach reliably here. The look is a translucent capsule, not native glass.
 * If a Compose view ever covers the bar, the capsule is hidden behind it;
 * that case is logged and only a phone test can settle it.
 *
 * 1.17 fixes ONLY how DragLensHook attaches: the drag overlay now
 * lives on the window decor, positioned over the bar — never as a
 * child of the bar. The 1.13/1.16 bisect proved the old attach (the
 * overlay as the bar's 6th child) made Instagram's bar controller
 * drop the tabs; the decor is outside that controller's reach. The
 * 1.15 probe cleared FullScreenHook, and the 1.16 re-probe proved
 * DragLensHook was the trigger, so this is the last suspect to fix.
 * The 1.11 capsule fix (TAG_CAPSULE_DRAWABLE identity check) is intact
 * and still the only thing standing between the capsule and Instagram's
 * own tab-bar controller replacing its background with a flat colour.
 * 1.19: the capsule flash on page switch. The global-layout
 * listener below re-applies when it notices the background is not
 * ours — but Instagram's bar controller can repaint the background
 * with a bare setBackgroundColor + invalidate, which fires NO layout
 * pass, so the flat frame stays until the next layout (or the next
 * 400 ms sweep). The fix is a pre-draw guard (watchActivity): before
 * every draw, if the bar is styled and its background is not the
 * capsule, re-apply synchronously and cancel that draw — so no
 * frame ever shows the flat background. See watchActivity.
 * 1.19.2: the tab-switch mess on Hossein's phone (feed pushed ~156dp
 * down, capsule gone, sometimes STUCK). The 1.19 guard checked only
 * the BACKGROUND — but Instagram re-adds/re-orders the wrapper's
 * children on tab switches, so the bar can be painted OVER by the
 * opaque feed while its background is still our capsule. The guard
 * is now a GEOMETRY guard (margins, elevation, draw order — bar must
 * be the last child of its parent), the fast path in apply() checks
 * measured geometry too, apply() re-asserts draw order with
 * bringToFront(), and the content panel is re-asserted on every
 * layout pass (FullScreenHook.assertPanelGeometry). See
 * work/rebuild-1.19.2/root-cause.md.
 */
object TabBarHook {

    private val NAV_TAB_NAMES = arrayOf(
        "feed_tab", "clips_tab", "search_tab", "creation_tab",
        "direct_tab", "news_tab", "profile_tab"
    )
    private val navTabIds = IntArray(NAV_TAB_NAMES.size)

    @Volatile
    private var idsResolved = false

    // Geometry, in dp — the iOS Liquid Glass capsule estimates from App Store
    // screenshots (outer platter ~87% of the width, ~64pt tall, capsule radius
    // ~half height, ~8pt gap above the bottom edge, selected highlight
    // ~52-56pt). Instagram publishes no design tokens, so these are the
    // documented estimates, not official values.
    private const val SIDE_MARGIN_DP = 16
    private const val BOTTOM_MARGIN_DP = 8
    private const val MIN_RADIUS_DP = 24
    private const val MAX_RADIUS_DP = 32
    private const val HIGHLIGHT_RADIUS_DP = 20
    private const val HIGHLIGHT_MIN_INSET_X_DP = 8
    private const val HIGHLIGHT_INSET_Y_DP = 6
    private const val HIGHLIGHT_WIDTH_DP = 54

    // View tags (module-local keys).
    private const val TAG_SAVED_STATE = 0x7e1e0301
    private const val TAG_APPLIED_SIGNATURE = 0x7e1e0302
    private const val TAG_PILL_NIGHT = 0x7e1e0303 // Boolean: which theme the tab's pill was built for
    private const val TAG_CAPSULE_DRAWABLE = 0x7e1e0304 // The capsule GradientDrawable last painted on the bar

    private val watchedDecors: MutableSet<View> =
        Collections.newSetFromMap(WeakHashMap<View, Boolean>())
    // Bars currently wearing the style (weak keys: a dead bar drops out by itself).
    private val styledBars: MutableSet<ViewGroup> =
        Collections.newSetFromMap(WeakHashMap<ViewGroup, Boolean>())

    @Volatile
    private var cachedBarRef: WeakReference<ViewGroup>? = null

    // Global layout fires many times per second on the main feed (video,
    // animations), so full sweeps triggered by layout are coalesced: at most
    // one pending sweep per window, run SWEEP_DEBOUNCE_MS later. The
    // selected-tab highlight is NOT debounced — it refreshes on the spot.
    private const val SWEEP_DEBOUNCE_MS = 400L
    private val MAIN = Handler(Looper.getMainLooper())
    private val pendingSweeps: MutableSet<View> =
        Collections.newSetFromMap(WeakHashMap<View, Boolean>())

    private var logged = false
    private var composeWarningLogged = false

    /** Everything the hook needs to undo, saved on the bar the first time it is styled. */
    private class SavedState {
        var background: Drawable? = null
        var marginLeft = 0
        var marginTop = 0
        var marginRight = 0
        var marginBottom = 0
        var elevation = 0f
        // Weak keys: a rebuilt tab view drops out by itself instead of pinning dead views.
        val tabBackgrounds: MutableMap<View, Drawable?> =
            Collections.synchronizedMap(WeakHashMap<View, Drawable?>())
        // A background drawable's own padding becomes the view's padding when it is set
        // (InsetDrawable included) and is NOT undone when the background is removed —
        // so each tab's original padding is saved next to its background.
        val tabPaddings: MutableMap<View, IntArray> =
            Collections.synchronizedMap(WeakHashMap<View, IntArray>())
        var divider: View? = null
        var dividerVisibility: Int = View.VISIBLE
    }

    // 1.19: pre-draw guard state. The guard runs before every draw,
    // so its fast path must be pointer-cheap (a WeakReference read, a
    // set lookup, a tag read, one identity compare). lastBarSearchMs
    // throttles the rebuilt-bar lookup (findBar walks the tree) to
    // once per 100 ms, and only while a bar was styled before.
    @Volatile
    private var lastBarSearchMs: Long = 0
    private var preDrawGuardLogged: Boolean = false

    // 1.19.3: the bar-bottom clamp (see wantedBottomMargin) logs once
    // per process — the clamp only fires when the inset is wrong, and
    // a settled layout never re-logs it.
    private var clampLogged: Boolean = false

    // 1.19.3 round 2: reusable scratch for getLocationInWindow in
    // wantedBottomMargin (main thread only — the guard and apply()
    // both run there). Avoids an allocation on the per-frame
    // pre-draw path.
    private val locScratch = IntArray(2)

    // 1.19.4: consecutive pre-draws cancelled in a row while a
    // mismatch persists (see guardAfterApply). The 1.19.3 single-shot
    // flag (cancelDrawOnce, Opus §3 round 2) let exactly the SECOND
    // consecutive broken frame through — the 1.19.3 probe's flat frame
    // (border-proven: pill-top edge pure white 255.0 in
    // shot_trans_r2h_0 vs 219.0 one second later). apply() cannot
    // always fix the mismatch on the first pass: it early-returns
    // when the bar is not laid out yet (height <= 0, the rebuilt bar
    // mid-switch), and bringToFront() only requests a layout, which
    // lands on the NEXT frame. So cancel again while the mismatch
    // persists, capped at GUARD_CANCEL_MAX_STREAK (~5 frames, ~80 ms
    // at 60 fps) so a parent genuinely fighting us can never blank
    // the screen for more than that — the anti-blank property Opus
    // §3 wanted, kept, with the hole closed. A clean pre-draw resets
    // the streak (see guardPreDraw).
    private const val GUARD_CANCEL_MAX_STREAK = 5
    private var guardCancelStreak: Int = 0

    /** Arm the hook for this activity. Called on every resume. */
    fun watchActivity(a: Activity?) {
        if (a == null) return
        // Nothing to do on a fresh start with the switch off — and nothing to restore.
        if (!Settings.isBarEnabled(a) && styledBars.isEmpty()) return
        try {
            ensureIds(a)
            sweep(a)
            val decor: View = a.window?.decorView ?: return
            if (!watchedDecors.add(decor)) return
            decor.viewTreeObserver.addOnGlobalLayoutListener {
                // Instant highlight: a tab tap switches pages (a layout pass), but the full
                // sweep is debounced — refresh the pill now so it moves with the tap.
                val cached = cachedBar()
                if (cached != null && activityOf(cached) == a && styledBars.contains(cached)
                    && Settings.isBarEnabled(a)
                ) {
                    // If Instagram's tab-bar controller replaced our capsule
                    // background with a flat color, re-apply now instead of only
                    // refreshing the highlight — so the flat flicker lasts at
                    // most one layout pass, not until the next 400 ms sweep.
                    // 1.19.2: the background is not the only thing
                    // Instagram rebuilds on a tab switch — it re-adds
                    // the wrapper's children (draw order) and resets
                    // the bar's margins/elevation. A capsule painted
                    // over is invisible even with the right background,
                    // so the fast check here is background AND measured
                    // geometry; anything wrong goes through apply().
                    val appliedCapsule = cached.getTag(TAG_CAPSULE_DRAWABLE) as? Drawable
                    if (cached.background === appliedCapsule && barGeometryOk(cached)) {
                        refreshHighlight(cached, isNight(cached))
                    } else {
                        apply(cached)
                    }
                    // Re-arm the drag overlay if Instagram rebuilt the
                    // bar (cheap no-op when present — re-syncs its
                    // position over the bar).
                    DragLensHook.attach(cached)
                }
                // 1.19.2: re-assert the content panel's geometry on
                // this layout pass itself (see assertPanelGeometry):
                // Instagram re-applies the window inset on tab
                // switches, and waiting for the debounced sweep would
                // let a broken frame paint. Cheap while the panel is
                // cached (two WeakReference reads).
                try {
                    FullScreenHook.assertPanelGeometry(a)
                } catch (ignored: Throwable) {
                }
                // 1.19.4: same rhythm for the feed LIST (see
                // assertFeedListGeometry): the 1.19.3 probe proved the
                // list can be registered as "content below the header"
                // and pinned at top 160 by convergeChrome, and nothing
                // re-asserted it — the bar got a geometry guard and
                // the panel got the assert above, but the list had no
                // per-layout re-assertion of its own.
                try {
                    FullScreenHook.assertFeedListGeometry(a)
                } catch (ignored: Throwable) {
                }
                if (!Settings.isBarEnabled(a) && styledBars.isEmpty()) return@addOnGlobalLayoutListener
                if (!pendingSweeps.add(decor)) return@addOnGlobalLayoutListener
                MAIN.postDelayed({
                    pendingSweeps.remove(decor)
                    sweep(a)
                }, SWEEP_DEBOUNCE_MS)
            }
            // 1.19: pre-draw guard — the capsule-flash fix. A layout
            // pass is NOT the only way the flat background appears:
            // Instagram's bar controller can repaint it with a bare
            // setBackgroundColor + invalidate, which draws flat with
            // no layout pass at all, so the listener above never
            // fires. This guard runs before EVERY draw instead: if
            // the bar is styled and its background is not our
            // capsule, re-apply synchronously and cancel this draw —
            // the next pass draws with the capsule, so no frame ever
            // shows the flat background. The fast path is pointer
            // reads only; the tree walk (a bar rebuilt by Instagram)
            // runs at most once per 100 ms and only while a bar was
            // styled before. Returning false is safe: after apply()
            // the background IS the capsule, so the re-run draw
            // passes the check and proceeds — it cannot loop.
            decor.viewTreeObserver.addOnPreDrawListener {
                try {
                    guardPreDraw(a, decor)
                } catch (ignored: Throwable) {
                    true
                }
            }
        } catch (ignored: Throwable) {
        }
    }

    /**
     * 1.19 pre-draw guard. Returns true to let the draw proceed,
     * false to cancel it (the draw is re-run after the fix).
     * 1.19.3 round 2: a cancel is armed at most once in a row (see
     * cancelDrawOnce) — if the parent is still settling and the
     * geometry is STILL wrong on the very next pre-draw, the frame
     * draws anyway instead of blanking the screen forever.
     */
    private fun guardPreDraw(a: Activity, decor: View): Boolean {
        if (!Settings.isBarEnabled(a)) return true
        val cached = cachedBar()
        if (cached != null && activityOf(cached) == a && styledBars.contains(cached)) {
            val appliedCapsule = cached.getTag(TAG_CAPSULE_DRAWABLE) as? Drawable
            if (cached.background !== appliedCapsule) {
                apply(cached)
                if (!preDrawGuardLogged) {
                    preDrawGuardLogged = true
                    RdxLog.d("capsule re-applied in pre-draw (flat background caught before draw)")
                } else {
                    RdxLog.d("capsule re-applied in pre-draw")
                }
                return guardAfterApply(cached)
            }
            // 1.19.2: the background is not enough. Instagram re-adds
            // the wrapper's children on tab switches (1.19.1 probe:
            // ui_step_tab04after has layout_container_main before the
            // pager), so the bar can be painted OVER by the opaque feed
            // while its background is still our capsule — invisible
            // with every old check passing. Verify MEASURED geometry
            // too: margins, elevation, and draw order (last child
            // wins). A failure re-applies synchronously and cancels
            // this draw, so no broken frame ever paints.
            if (!barGeometryOk(cached)) {
                apply(cached)
                RdxLog.d("geometry guard: bar geometry wrong, re-applied in pre-draw")
                return guardAfterApply(cached)
            }
            guardCancelStreak = 0
            return true
        }
        // No cached bar: Instagram may have rebuilt it on the page
        // switch (the old instance is detached). Look for the new one,
        // throttled — a tree walk on every frame would cost more
        // than the flash it prevents.
        if (styledBars.isEmpty()) return true
        val now = android.os.SystemClock.uptimeMillis()
        if (now - lastBarSearchMs < 100L) return true
        lastBarSearchMs = now
        val root = decor as? ViewGroup ?: return true
        val bar = findBar(a, root) ?: return true
        cachedBarRef = WeakReference(bar)
        apply(bar)
        RdxLog.d("capsule re-applied in pre-draw (rebuilt bar found)")
        // One cancel to let the fix land. No streak here: if apply()
        // could not fix it (bar not laid out yet), the next pre-draw
        // takes the cached-bar branch above, where guardAfterApply
        // bounds the cancels — a repeated cancel in THIS branch would
        // blank screens where Instagram legitimately has no tab bar.
        return false
    }

    /**
     * 1.19.4: after apply(), did the mismatch actually clear? apply()
     * cannot always fix it on the first pass — it early-returns when
     * the bar is not laid out yet (height <= 0, the rebuilt bar
     * mid-switch), and bringToFront() only requests a layout, which
     * lands on the NEXT frame. In both cases the very next pre-draw
     * still finds the mismatch, and the old cancelDrawOnce() let
     * exactly that frame through (its second consecutive call returns
     * true) — the 1.19.3 probe's flat frame (border-proven, see
     * root-cause.md defect (b)). So: cancel again while the mismatch
     * persists, bounded (max GUARD_CANCEL_MAX_STREAK consecutive
     * cancels, ~80 ms at 60 fps) so a parent genuinely fighting us
     * can never blank the screen for more than that — the anti-blank
     * property Opus §3 wanted, kept, with the hole closed. A clean
     * pre-draw resets the streak (see guardPreDraw), and the cap
     * resets it too, so the next real break is caught again.
     * barGeometryOk is read-only (tag reads + int compares), so this
     * re-check cannot re-enter apply() or spin a layout loop. No
     * requestLayout() is ever called from this callback — apply()
     * only sets layout params, the standard mechanism.
     */
    private fun guardAfterApply(bar: ViewGroup): Boolean {
        val appliedCapsule = bar.getTag(TAG_CAPSULE_DRAWABLE) as? Drawable
        val fixed = bar.background === appliedCapsule && barGeometryOk(bar)
        if (fixed) {
            guardCancelStreak = 0
            return false // one cancel to let the fix land
        }
        if (guardCancelStreak < GUARD_CANCEL_MAX_STREAK) {
            guardCancelStreak++
            return false
        }
        guardCancelStreak = 0
        return true // bound reached: let one frame through, then re-arm
    }

    /**
     * 1.19.3: the ONE place that computes the bar's wanted bottom
     * margin — used by BOTH apply() (sets it) and barGeometryOk()
     * (checks it). Single source of truth, so a margin this function
     * produces always satisfies the guard: after one application the
     * geometry is stable by construction, and no per-frame loop is
     * possible (no streak breaker needed).
     *
     * The formula is the saved stock margin + 8dp + the CURRENT
     * bottomInsetPx (a re-measured inset forces a re-apply). On top
     * of that, a safety clamp: if FullScreenHook knows the system
     * nav bar's top edge (navBarTopPx > 0) AND the bar is
     * bottom-anchored (its measured bottom is parent.height -
     * current lp.bottomMargin, ±2 px — otherwise the margin does
     * not control the bottom and clamping it would fight a layout
     * we do not understand), the bar's bottom must not pass the nav
     * bar's top edge. If the formula margin would put it there, the
     * margin is raised so the bar lands exactly at the nav-bar top
     * instead of under it. With the inset fixed (96 px on the
     * emulator) the clamp never fires — bottom 112 px lands the bar
     * at 1168, 16 px above the nav bar; it only fires if the inset
     * is wrong, and then it is the backstop that keeps the taps in
     * the app instead of on SystemUI.
     *
     * IDEMPOTENCE (1.19.3 round 2 — Opus §3, verified by
     * construction): the clamped value is parent.height − maxBottom,
     * where maxBottom = navTop − parentWinTop — computed ONLY from
     * the parent's geometry and the nav-bar top. The bar's current
     * bottom appears solely in the ±2 px bottom-anchored guard, never
     * in the value, so re-applying a clamped margin returns the same
     * number on every frame: after clamping, bar.bottom ==
     * parent.height − clamped == maxBottom, the guard still passes,
     * and the formula margin is unchanged, so the clamp recomputes
     * identically. The equality short-circuit lives in the callers
     * (barGeometryOk returns true when lp.bottomMargin ==
     * wantedBottomMargin; apply() only writes when a margin
     * differs), so a settled layout never re-applies. Opus's
     * suggested form (margin = max(base, parentBottom − navTop +
     * base)) was NOT pasted: it double-counts the base (on the
     * emulator: max(112, 1280 − 1184 + 112) = 208 → bar bottom
     * 1072, 96 px too high). The correct safe form is
     * max(base, parent.height − maxBottom), which is exactly what
     * the clamp below computes.
     */
    private fun wantedBottomMargin(bar: ViewGroup, saved: SavedState): Int {
        val bottom = saved.marginBottom + dp(bar, BOTTOM_MARGIN_DP) +
            FullScreenHook.bottomInsetPx
        try {
            val navTop = FullScreenHook.navBarTopPx
            if (navTop > 0) {
                val lp = bar.layoutParams as? ViewGroup.MarginLayoutParams
                val parent = bar.parent as? ViewGroup
                if (lp != null && parent != null && parent.height > 0) {
                    // Only when bottom-anchored: the margin controls
                    // the bottom edge (bar.bottom is parent-relative).
                    if (Math.abs(bar.bottom - (parent.height - lp.bottomMargin)) <= 2) {
                        // The parent's WINDOW top — getLocationInWindow
                        // is translationY-aware (the old manual walk
                        // summing getTop() ignored the hide/show
                        // animation IG runs on its bars, so the clamp
                        // could fight it) and a single call, which
                        // matters on the per-frame path. navBarTopPx
                        // is window coords too (see
                        // FullScreenHook.measureBottomInset), so the
                        // two are directly comparable. On the
                        // emulator: parent top 0, navTop 1184 →
                        // maxBottom 1184, clamped 1280 − 1184 = 96 —
                        // the same value the walk computed.
                        parent.getLocationInWindow(locScratch)
                        val parentWinTop = locScratch[1]
                        val maxBottom = navTop - parentWinTop
                        if (parent.height - bottom > maxBottom) {
                            val clamped = parent.height - maxBottom
                            if (!clampLogged) {
                                clampLogged = true
                                RdxLog.d(
                                    "bar bottom clamped to nav bar top " +
                                        "(margin " + bottom + " -> " + clamped + ")"
                                )
                            }
                            return clamped
                        }
                    }
                }
            }
        } catch (ignored: Throwable) {
        }
        return bottom
    }

    /**
     * 1.19.2: is the bar's MEASURED geometry what apply() set?
     * Margins (against the CURRENT bottomInsetPx — a re-measured inset
     * forces a re-apply), elevation 0, and the bar the last child of
     * its parent (later child = painted on top; Instagram re-orders
     * the wrapper's children on tab switches). Cheap: tag reads and
     * int compares only, so the pre-draw guard can run it on every
     * frame. Returns true when there is nothing to check (no saved
     * state / no margin params) so the guard never blocks a draw on
     * a bar apply() has not styled yet.
     */
    private fun barGeometryOk(bar: ViewGroup): Boolean {
        try {
            val saved = bar.getTag(TAG_SAVED_STATE) as? SavedState ?: return true
            val lp = bar.layoutParams as? ViewGroup.MarginLayoutParams
            if (lp != null) {
                val wantLeft = saved.marginLeft + dp(bar, SIDE_MARGIN_DP)
                val wantRight = saved.marginRight + dp(bar, SIDE_MARGIN_DP)
                // 1.19.3: the wanted margin comes from the shared
                // helper (same function apply() uses to set it), so a
                // clamped margin satisfies this check.
                val wantBottom = wantedBottomMargin(bar, saved)
                if (lp.leftMargin != wantLeft || lp.rightMargin != wantRight ||
                    lp.bottomMargin != wantBottom
                ) return false
            }
            if (bar.elevation != 0f) return false
            val parent = bar.parent as? ViewGroup
            if (parent != null && parent.childCount > 0 &&
                parent.getChildAt(parent.childCount - 1) !== bar
            ) return false
            return true
        } catch (ignored: Throwable) {
            return true
        }
    }

    private fun cachedBar(): ViewGroup? {
        val ref = cachedBarRef ?: return null
        val bar = ref.get()
        return if (bar != null && bar.isAttachedToWindow) bar else null
    }

    /** The Activity a view was inflated in (unwrapping ContextThemeWrappers). */
    private fun activityOf(v: View): Activity? {
        var c: Context? = v.context
        while (c is ContextWrapper) {
            if (c is Activity) return c
            c = c.baseContext
        }
        return c as? Activity
    }

    @SuppressLint("DiscouragedApi")
    private fun ensureIds(a: Activity) {
        if (idsResolved) return
        try {
            val res = a.resources
            val pkg = a.packageName
            for (i in NAV_TAB_NAMES.indices) {
                navTabIds[i] = res.getIdentifier(NAV_TAB_NAMES[i], "id", pkg)
            }
            // Only remember success: if the ids come back 0 (resources not ready yet),
            // the next resume retries instead of disabling the hook for the whole process.
            if (navTabIds[0] != 0) idsResolved = true
        } catch (ignored: Throwable) {
        }
    }

    private fun sweep(a: Activity?) {
        // The debounced runnable can outlive its activity (rotation, quick back press).
        if (a == null || a.isFinishing || a.isDestroyed) return
        // Full-screen runs on every sweep too (not only when the bar is
        // found): the feed geometry is per-tab and Instagram resets it as
        // you navigate, so it needs the same re-application rhythm.
        try {
            FullScreenHook.apply(a)
        } catch (ignored: Throwable) {
        }
        try {
            val root = a.window?.decorView as? ViewGroup ?: return
            var bar = cachedBar()
            if (bar == null || activityOf(bar) != a) bar = findBar(a, root)
            if (bar == null) return
            cachedBarRef = WeakReference(bar)
            if (Settings.isBarEnabled(a)) apply(bar) else restore(bar)
        } catch (ignored: Throwable) {
        }
    }

    /**
     * The bar is the parent of feed_tab. It is only trusted when at least four of the
     * known tabs are its direct children and it spans most of the screen width — a tab
     * strip inside a bottom sheet or a dialog is narrower and holds fewer tabs.
     */
    private fun findBar(a: Activity, root: ViewGroup): ViewGroup? {
        if (navTabIds[0] == 0) return null
        val feed = root.findViewById<View>(navTabIds[0]) ?: return null
        val bar = feed.parent as? ViewGroup ?: return null
        var tabs = 0
        for (i in 0 until bar.childCount) {
            val id = bar.getChildAt(i).id
            for (tabId in navTabIds) {
                if (id != 0 && id == tabId) {
                    tabs++
                    break
                }
            }
        }
        if (tabs < 4) return null
        val screenWidth = a.resources.displayMetrics.widthPixels
        if (bar.width.toFloat() < screenWidth * 0.8f) return null
        return bar
    }

    private fun isNight(v: View): Boolean {
        return (v.resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK) ==
            Configuration.UI_MODE_NIGHT_YES
    }

    private fun dp(v: View, dp: Int): Int {
        return Math.round(dp * v.resources.displayMetrics.density)
    }

    private fun apply(bar: ViewGroup) {
        try {
            val height = bar.height
            if (height <= 0) return // not laid out yet — the layout listener fires again
            val night = isNight(bar)
            val density = bar.resources.displayMetrics.density
            val radius = Math.min(
                MAX_RADIUS_DP,
                Math.max(MIN_RADIUS_DP, Math.round(height / 2f / density))
            )
            val radiusPx = dp(bar, radius)
            val signature = (if (night) 0x10000 else 0) or radiusPx
            val applied = bar.getTag(TAG_APPLIED_SIGNATURE)
            // The capsule we painted is remembered on the bar. Instagram's own
            // tab-bar controller (X/00YD.A0K -> A0P) replaces any background
            // that is not its X/00xO drawable with a flat color, so a matching
            // signature alone does NOT prove the capsule is still there.
            // Re-apply when the background is not ours.
            val appliedCapsule = bar.getTag(TAG_CAPSULE_DRAWABLE) as? Drawable
            // 1.19.2: the fast path used to trust (signature +
            // background) alone. Instagram re-orders the wrapper's
            // children and resets the bar's margins/elevation on tab
            // switches, so a bar can pass those checks while being
            // painted over or sitting in the wrong place — and the
            // broken state then sticks, because nothing re-asserts
            // it. The fast path now also requires the MEASURED
            // geometry to match; anything wrong falls through to the
            // full apply below, which re-sets margins, elevation and
            // draw order.
            if (applied is Int && applied == signature && styledBars.contains(bar)
                && bar.background === appliedCapsule && barGeometryOk(bar)) {
                // Same theme, same size, same geometry — only the selected tab may have moved.
                refreshHighlight(bar, night)
                DragLensHook.attach(bar)
                return
            }

            var saved = bar.getTag(TAG_SAVED_STATE) as? SavedState
            if (saved == null) {
                saved = SavedState()
                saved.background = bar.background
                val lp = bar.layoutParams
                if (lp is ViewGroup.MarginLayoutParams) {
                    saved.marginLeft = lp.leftMargin
                    saved.marginTop = lp.topMargin
                    saved.marginRight = lp.rightMargin
                    saved.marginBottom = lp.bottomMargin
                }
                saved.elevation = bar.elevation
                bar.setTag(TAG_SAVED_STATE, saved)
            }

            // Capsule, liquid-glass style (1.13, kept in the 1.14 bisect):
            // a vertical gradient — light at the top edge, deeper at the
            // bottom — over a translucent fill, with a thin light border.
            // The fill is deliberately more translucent than the old
            // solid 60%/70% so the feed shows through the capsule itself,
            // while everything behind and around it stays fully
            // transparent (no blur anywhere near the capsule).
            val capsule = GradientDrawable()
            capsule.shape = GradientDrawable.RECTANGLE
            capsule.cornerRadius = radiusPx.toFloat()
            capsule.orientation = GradientDrawable.Orientation.TOP_BOTTOM
            if (night) {
                capsule.colors = intArrayOf(
                    Color.argb(64, 255, 255, 255), // white 25%: top-edge light
                    Color.argb(96, 0, 0, 0), // black ~38%
                    Color.argb(115, 0, 0, 0) // black 45%: bottom depth
                )
                capsule.setStroke(dp(bar, 1), Color.argb(77, 255, 255, 255)) // white, 30%
            } else {
                capsule.colors = intArrayOf(
                    Color.argb(153, 255, 255, 255), // white 60%: top-edge light
                    Color.argb(115, 255, 255, 255), // white 45%
                    Color.argb(128, 255, 255, 255) // white 50%: bottom depth
                )
                capsule.setStroke(dp(bar, 1), Color.argb(36, 0, 0, 0)) // black, 14%
            }
            bar.background = capsule
            bar.setTag(TAG_CAPSULE_DRAWABLE, capsule)

            // Float it: side margins + a gap above the bottom edge, ADDED to whatever
            // margins Instagram already gave the bar. Instagram runs edge-to-edge, so the
            // stock bottom margin can carry the system navigation inset — overwriting it
            // would drop the bar under the system buttons on 3-button navigation.
            // 1.19: FullScreenHook grows the coordinator to the true bottom, which
            // would carry a bottom-anchored bar down by the nav inset; the inset
            // is added here so the capsule stays exactly where it was. If the
            // bar is top-positioned instead, this extra bottom margin is inert.
            // setLayoutParams is only called when something actually changed, so styling
            // never spins a re-entrant layout loop.
            val lp = bar.layoutParams
            if (lp is ViewGroup.MarginLayoutParams) {
                val left = saved.marginLeft + dp(bar, SIDE_MARGIN_DP)
                val right = saved.marginRight + dp(bar, SIDE_MARGIN_DP)
                // 1.19.3: the wanted margin comes from the shared
                // helper (same function barGeometryOk() checks), with
                // the nav-bar clamp as a backstop.
                val bottom = wantedBottomMargin(bar, saved)
                if (lp.leftMargin != left || lp.rightMargin != right || lp.bottomMargin != bottom) {
                    lp.leftMargin = left
                    lp.rightMargin = right
                    lp.bottomMargin = bottom
                    bar.layoutParams = lp
                }
            }

            bar.elevation = 0f // iOS glass has no heavy shadow

            // 1.19.2: draw order. Instagram re-adds the wrapper's
            // children on tab switches (1.19.1 probe:
            // ui_step_tab04after has layout_container_main before
            // the pager); the bar is only visible while it is the
            // LAST child of its parent — later child = painted on
            // top. Elevation 0 alone does not save it. Re-asserted on
            // every full apply; the guard and the fast path above
            // check it, so a settled layout never calls this twice.
            val parent = bar.parent as? ViewGroup
            if (parent != null && parent.childCount > 0 &&
                parent.getChildAt(parent.childCount - 1) !== bar
            ) {
                bar.bringToFront()
                RdxLog.d("bar brought to front (draw order changed by Instagram)")
            }

            hideDivider(bar, saved)
            warnIfComposeCovered(bar)
            refreshHighlight(bar, night)
            DragLensHook.attach(bar)

            bar.setTag(TAG_APPLIED_SIGNATURE, signature)
            styledBars.add(bar)
            if (!logged) {
                logged = true
                RdxLog.d(
                    "styled bar: h=" + height + " radius=" + radius +
                        "dp night=" + night +
                        " margins=" + (lp is ViewGroup.MarginLayoutParams)
                )
            }
        } catch (ignored: Throwable) {
        }
    }

    /**
     * The selected tab gets a smaller translucent pill behind its icon (the iOS highlight,
     * ~54dp wide and centred); the others keep theirs off. A tab is recognised as "ours"
     * by its tag, never by the drawable type — Instagram itself may use InsetDrawables too.
     */
    private fun refreshHighlight(bar: ViewGroup, night: Boolean) {
        try {
            val saved = bar.getTag(TAG_SAVED_STATE) as? SavedState
            for (i in 0 until bar.childCount) {
                val child = bar.getChildAt(i)
                var isTab = false
                for (tabId in navTabIds) {
                    if (child.id != 0 && child.id == tabId) {
                        isTab = true
                        break
                    }
                }
                if (!isTab) continue
                if (child.isSelected) {
                    // Pill already on with the right theme — nothing to do (and no new drawable).
                    if (child.getTag(TAG_PILL_NIGHT) as? Boolean == night) continue
                    if (saved != null && child.getTag(TAG_PILL_NIGHT) == null &&
                        !saved.tabBackgrounds.containsKey(child)
                    ) {
                        // Only while no pill is on: the background read now is the true
                        // original. (putIfAbsent is NOT enough here — a tab's original
                        // background is usually null, and putIfAbsent treats a null
                        // mapping as absent, so a later rebuild would overwrite it with
                        // the old pill itself and the highlight could never be removed.)
                        saved.tabBackgrounds[child] = child.background
                        saved.tabPaddings[child] = intArrayOf(
                            child.paddingLeft, child.paddingTop,
                            child.paddingRight, child.paddingBottom
                        )
                    }
                    val pill = GradientDrawable()
                    pill.shape = GradientDrawable.RECTANGLE
                    pill.cornerRadius = dp(bar, HIGHLIGHT_RADIUS_DP).toFloat()
                    pill.setColor(
                        if (night) Color.argb(31, 255, 255, 255) else Color.argb(20, 0, 0, 0)
                    ) // white 12% / black 8%
                    val insetX = Math.max(
                        dp(bar, HIGHLIGHT_MIN_INSET_X_DP),
                        (child.width - dp(bar, HIGHLIGHT_WIDTH_DP)) / 2
                    )
                    child.background = InsetDrawable(
                        pill,
                        insetX, dp(bar, HIGHLIGHT_INSET_Y_DP),
                        insetX, dp(bar, HIGHLIGHT_INSET_Y_DP)
                    )
                    // The InsetDrawable's insets become the view's padding when set —
                    // put the tab's own padding straight back so icons/badges don't shift.
                    val pad = saved?.tabPaddings?.get(child)
                    if (pad != null) child.setPadding(pad[0], pad[1], pad[2], pad[3])
                    child.setTag(TAG_PILL_NIGHT, night)
                } else if (child.getTag(TAG_PILL_NIGHT) != null) {
                    val original: Drawable? = saved?.tabBackgrounds?.get(child)
                    child.background = original
                    val pad = saved?.tabPaddings?.get(child)
                    if (pad != null) child.setPadding(pad[0], pad[1], pad[2], pad[3])
                    child.setTag(TAG_PILL_NIGHT, null)
                }
            }
        } catch (ignored: Throwable) {
        }
    }

    /** A hairline divider child of the bar (<=2dp tall, near full width) breaks the capsule look. */
    private fun hideDivider(bar: ViewGroup, saved: SavedState) {
        try {
            // Instagram rebuilds the bar's children as you navigate; a saved divider that is
            // no longer a child of this bar is stale — drop it and look for the new one.
            if (saved.divider != null && saved.divider?.parent != bar) {
                saved.divider = null
            }
            if (saved.divider != null) {
                // Still ours — but Instagram may have shown it again; keep it hidden.
                if (saved.divider?.visibility != View.GONE) saved.divider?.visibility = View.GONE
                return
            }
            val maxH = dp(bar, 2)
            for (i in 0 until bar.childCount) {
                val child = bar.getChildAt(i)
                if (child.height > 0 && child.height <= maxH &&
                    child.width.toFloat() >= bar.width * 0.9f
                ) {
                    saved.divider = child
                    saved.dividerVisibility = child.visibility
                    child.visibility = View.GONE
                    return
                }
            }
        } catch (ignored: Throwable) {
        }
    }

    /**
     * If a Compose view fills the bar, it draws its own opaque strip over our capsule.
     * We cannot restyle inside it from a view hook — log once so the phone test can confirm.
     */
    private fun warnIfComposeCovered(bar: ViewGroup) {
        if (composeWarningLogged) return
        try {
            for (i in 0 until bar.childCount) {
                val child = bar.getChildAt(i)
                val name = child.javaClass.name
                if (name.contains("AndroidComposeView") &&
                    child.width.toFloat() >= bar.width * 0.9f &&
                    child.height.toFloat() >= bar.height * 0.9f
                ) {
                    composeWarningLogged = true
                    RdxLog.d("Compose child covers the bar — capsule may be hidden behind it")
                    return
                }
            }
        } catch (ignored: Throwable) {
        }
    }

    /** Return the bar to exactly how Instagram drew it, and forget the saved state. */
    private fun restore(bar: ViewGroup) {
        try {
            DragLensHook.detach(bar)
            val saved = bar.getTag(TAG_SAVED_STATE) as? SavedState ?: return
            // A saved background belongs to the theme that was active when the bar was
            // first styled; if the theme changed since, it is stale — but an opaque stale
            // background still beats a transparent bar, which would let the feed show
            // through behind the tabs. (In practice a theme change recreates the activity
            // and the bar, so this is only a fallback.)
            bar.background = saved.background
            val lp = bar.layoutParams
            if (lp is ViewGroup.MarginLayoutParams) {
                lp.leftMargin = saved.marginLeft
                lp.topMargin = saved.marginTop
                lp.rightMargin = saved.marginRight
                lp.bottomMargin = saved.marginBottom
                bar.layoutParams = lp
            }
            bar.elevation = saved.elevation
            for ((view, bg) in saved.tabBackgrounds) {
                view.background = bg
                view.setTag(TAG_PILL_NIGHT, null)
                val pad = saved.tabPaddings[view]
                if (pad != null) view.setPadding(pad[0], pad[1], pad[2], pad[3])
            }
            saved.tabBackgrounds.clear()
            saved.tabPaddings.clear()
            if (saved.divider != null) {
                saved.divider?.visibility = saved.dividerVisibility
                saved.divider = null
            }
            bar.setTag(TAG_SAVED_STATE, null)
            bar.setTag(TAG_APPLIED_SIGNATURE, null)
            bar.setTag(TAG_CAPSULE_DRAWABLE, null)
            styledBars.remove(bar)
            RdxLog.d("restored stock bar")
        } catch (ignored: Throwable) {
        }
    }
}
