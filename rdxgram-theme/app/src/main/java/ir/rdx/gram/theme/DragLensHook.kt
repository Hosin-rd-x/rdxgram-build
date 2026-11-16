package ir.rdx.gram.theme

import android.animation.Animator
import android.animation.AnimatorListenerAdapter
import android.animation.ValueAnimator
import android.content.res.Configuration
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.ViewGroup
import android.view.animation.OvershootInterpolator
import android.widget.FrameLayout
import java.lang.ref.WeakReference
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

/**
 * Full drag animation between tabs for RdxGram (the "drag lens").
 * 1.17: the overlay attaches to the window decor, never inside the bar —
 * the 1.13/1.16 bisect proved the bar-child attach emptied the tab bar.
 * 1.17.1: the overlay owns the gesture by consuming DOWN (see below) —
 * the 1.17 intercept-on-MOVE design could never fire for a sibling
 * overlay (re-probe 4: swipe never showed a lens, never switched tabs).
 * See the attach() doc below.
 *
 * Stock Instagram 451 has NO drag on the tab bar — tabs only switch on
 * tap. This builds it in the theme module, on top of the capsule:
 *
 *  - a transparent overlay sits over the bar — but NOT as a child of the
 *    bar. It is attached to the activity window's decor view (a
 *    FrameLayout by construction), positioned exactly over the bar's
 *    bounds, so it always covers exactly the bar and draws above the
 *    tabs. This is the 1.17 fix: in 1.13/1.16 the overlay was a child
 *    of the bar itself (bar.addView, the 6th child), and the bisect
 *    proved Instagram's bar controller drops/rebuilds the tabs when a
 *    foreign child appears inside the bar — the bar came up with
 *    exactly one empty child and all five tabs gone. The decor is
 *    outside the bar controller's reach: it never rebuilds the decor's
 *    children, and attaching a view there (the same class of operation
 *    as FullScreenHook's window work, cleared by the 1.15 probe) leaves
 *    the bar's children untouched. It is a ViewGroup that OWNS every
 *    gesture by consuming DOWN (1.17.1): the 1.17 design tried to NOT
 *    intercept on DOWN and intercept only once the finger had moved
 *    horizontally past an 8dp threshold — that can never work for a
 *    sibling overlay. Android delivers a gesture's MOVE/UP events only
 *    through the ancestors of the view that received DOWN, and a
 *    sibling overlay's onInterceptTouchEvent is consulted exactly once
 *    per gesture (for the DOWN it returns false for), so the drag
 *    machine was unreachable dead code: re-probe 4 proved the swipe
 *    never showed a lens and never switched tabs, while all 8 taps
 *    landed fine. So now onTouchEvent returns true for ACTION_DOWN
 *    (the overlay becomes the touch target), plain taps are emulated
 *    with performClick on UP, long-press is forwarded with
 *    performLongClick after the system timeout, and only a horizontal
 *    move past 8dp (further sideways than vertically) starts the
 *    drag. Because the overlay covers the bar exactly, its touch
 *    coordinates ARE the bar's coordinates, so tab lookup needs no
 *    conversion.
 *  - while dragging, a glass lens pill follows the finger's x (with a
 *    small stretch, up to ~12%, the further it is pulled from where
 *    the drag started);
 *  - on release past the midpoint between two tabs it switches to that
 *    tab (a plain performClick on the tab — the same path a tap takes),
 *    and the lens settles onto the tab's centre with a ValueAnimator +
 *    OvershootInterpolator spring, then fades away;
 *  - on release without crossing a midpoint the finger's tab is the
 *    target anyway (nearest tab wins), so a drag always lands on a tab;
 *  - long-press is forwarded: if the finger stays down past the
 *    system long-press timeout without dragging, the tab under the
 *    finger gets performLongClick — the same path a real long-press
 *    ends in (the tab never gets DOWN directly, the overlay owns the
 *    gesture, so it must forward both tap and long-press itself);
 *  - TalkBack is unaffected: the overlay reports
 *    IMPORTANT_FOR_ACCESSIBILITY_NO and the tabs stay readable.
 *
 * Robustness: the overlay is only armed when at least two tabs resolve
 * to distinct centres. If a drag target cannot be resolved at release
 * time, nothing is clicked and the lens just hides — the worst case is
 * a drag that does nothing, never a dead tab bar. Everything is
 * try/catch-guarded. The hook owns exactly one overlay at a time
 * (attachedOverlay): when Instagram rebuilds the bar, the next attach
 * retires the overlay that points at the dead bar before arming a new
 * one — the old design got this for free because the overlay died with
 * its parent bar, but a decor overlay outlives the bar, so the
 * retirement must be explicit. TabBarHook.apply() re-attaches on every
 * layout pass, which also re-syncs the overlay's position if the bar
 * moved or resized.
 */
object DragLensHook {

    private const val TAG_DRAG_OVERLAY = 0x7e1e0312

    // The overlay lives on the window decor, NOT inside the bar (1.17 —
    // see the class doc). Exactly one overlay is owned at a time: a
    // decor overlay outlives the bar it covers, so when Instagram
    // rebuilds the bar the next attach() must retire the stale one
    // explicitly, or drags would keep clicking the dead bar's tabs.
    private var attachedOverlay: DragOverlay? = null
    private var attachedBarRef: WeakReference<ViewGroup>? = null

    // Tap vs drag: below this horizontal move it is still a tap.
    private const val DRAG_THRESHOLD_DP = 8
    // Lens pill width; the selected-tab highlight pill is 54dp, the lens
    // is deliberately a little wider so it reads as a magnifier, not the pill.
    private const val LENS_WIDTH_DP = 72
    private const val LENS_STRETCH_MAX = 0.12f
    private const val SETTLE_MS = 260L

    private val NAV_TAB_NAMES = arrayOf(
        "feed_tab", "clips_tab", "search_tab", "creation_tab",
        "direct_tab", "news_tab", "profile_tab"
    )

    /** Attach the drag overlay over a styled bar. Idempotent. */
    fun attach(bar: ViewGroup) {
        try {
            // Same bar, overlay still on the decor: just re-sync its
            // bounds — the bar moves/resizes as you navigate.
            val existing = attachedOverlay
            if (existing != null && attachedBarRef?.get() === bar && existing.parent != null) {
                positionOverlay(existing, bar)
                return
            }
            // Different bar (Instagram rebuilt it), or the overlay was
            // dropped: retire the stale one before arming a new one.
            retireOverlay()
            if (tabCenters(bar).size < 2) {
                RdxLog.d("drag attach skipped: fewer than 2 tab centres resolve")
                return // cannot resolve targets: leave taps alone
            }
            if (bar.width <= 0 || bar.height <= 0) {
                RdxLog.d("drag attach skipped: bar not laid out yet")
                return // not laid out yet
            }
            // The decor is the window root (a FrameLayout by
            // construction); absolute positioning via margins is safe
            // there and never disturbs the content layout. rootView is
            // the bar itself while it is not attached to a window yet.
            val decor = bar.rootView as? ViewGroup
            if (decor == null) {
                RdxLog.d("drag attach skipped: no decor (rootView is not a ViewGroup)")
                return
            }
            if (decor === bar) {
                RdxLog.d("drag attach skipped: decor is the bar itself (not attached to a window yet)")
                return
            }
            val overlay = DragOverlay(bar)
            overlay.isClickable = false
            overlay.isFocusable = false
            overlay.importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
            positionOverlay(overlay, bar)
            decor.addView(overlay)
            attachedOverlay = overlay
            attachedBarRef = WeakReference(bar)
            bar.setTag(TAG_DRAG_OVERLAY, overlay)
            val lp = overlay.layoutParams as? FrameLayout.LayoutParams
            RdxLog.d(
                "drag overlay attached: bar " + bar.width + "x" + bar.height +
                    " overlay " + (lp?.width ?: -1) + "x" + (lp?.height ?: -1) +
                    " margins (" + (lp?.leftMargin ?: -1) + "," + (lp?.topMargin ?: -1) + ")"
            )
        } catch (ignored: Throwable) {
        }
    }

    /**
     * Place [overlay] exactly over [bar]'s bounds, in decor coordinates.
     * The overlay's touch coordinates are then the bar's coordinates, so
     * no conversion is needed anywhere else. No-op when the bar is not
     * laid out yet — the next layout pass re-arms and re-syncs.
     */
    private fun positionOverlay(overlay: DragOverlay, bar: ViewGroup) {
        try {
            val w = bar.width
            val h = bar.height
            if (w <= 0 || h <= 0) return
            val decor = overlay.parent as? ViewGroup ?: bar.rootView as? ViewGroup ?: return
            val barLoc = IntArray(2)
            val decorLoc = IntArray(2)
            bar.getLocationInWindow(barLoc)
            decor.getLocationInWindow(decorLoc)
            val lp = FrameLayout.LayoutParams(w, h)
            lp.gravity = Gravity.TOP or Gravity.START
            lp.leftMargin = barLoc[0] - decorLoc[0]
            lp.topMargin = barLoc[1] - decorLoc[1]
            overlay.layoutParams = lp
        } catch (ignored: Throwable) {
        }
    }

    /** Remove the owned overlay from wherever it is attached. */
    private fun retireOverlay() {
        try {
            val overlay = attachedOverlay ?: return
            attachedOverlay = null
            val oldBar = attachedBarRef?.get()
            attachedBarRef = null
            (overlay.parent as? ViewGroup)?.removeView(overlay)
            oldBar?.setTag(TAG_DRAG_OVERLAY, null)
        } catch (ignored: Throwable) {
        }
    }

    /** Remove the overlay (called from TabBarHook.restore()). */
    fun detach(bar: ViewGroup) {
        try {
            // The owned overlay belongs to this bar: retire it.
            if (attachedBarRef?.get() === bar) {
                retireOverlay()
                return
            }
            // Fallback: an overlay tagged on this bar but not owned
            // (e.g. armed before a process restart) — remove it too.
            val overlay = bar.getTag(TAG_DRAG_OVERLAY) as? View ?: return
            (overlay.parent as? ViewGroup)?.removeView(overlay)
            bar.setTag(TAG_DRAG_OVERLAY, null)
        } catch (ignored: Throwable) {
        }
    }

    /** Centres (x, in bar coordinates) of the bar's tabs, left to right. */
    private fun tabCenters(bar: ViewGroup): List<Float> {
        val ids = resolveTabIds(bar)
        val centres = ArrayList<Float>()
        try {
            for (i in 0 until bar.childCount) {
                val child = bar.getChildAt(i) ?: continue
                var isTab = false
                for (tabId in ids) {
                    if (child.id != 0 && child.id == tabId) {
                        isTab = true
                        break
                    }
                }
                if (!isTab) continue
                if (child.width <= 0) continue
                centres.add(child.left + child.width / 2f)
            }
        } catch (ignored: Throwable) {
        }
        centres.sort()
        return centres
    }

    /** The tab view whose centre is nearest to x (bar coordinates), or null. */
    private fun nearestTab(bar: ViewGroup, x: Float): View? {
        val ids = resolveTabIds(bar)
        var best: View? = null
        var bestDist = Float.MAX_VALUE
        try {
            for (i in 0 until bar.childCount) {
                val child = bar.getChildAt(i) ?: continue
                var isTab = false
                for (tabId in ids) {
                    if (child.id != 0 && child.id == tabId) {
                        isTab = true
                        break
                    }
                }
                if (!isTab || child.width <= 0) continue
                val centre = child.left + child.width / 2f
                val dist = abs(centre - x)
                if (dist < bestDist) {
                    bestDist = dist
                    best = child
                }
            }
        } catch (ignored: Throwable) {
        }
        return best
    }

    // Tab resource ids, resolved once per process (same pattern as TabBarHook).
    @Volatile
    private var resolvedIds: IntArray? = null

    private fun resolveTabIds(bar: View): IntArray {
        resolvedIds?.let { return it }
        val ids = IntArray(NAV_TAB_NAMES.size)
        try {
            val res = bar.resources
            val pkg = bar.context.packageName
            for (i in NAV_TAB_NAMES.indices) {
                ids[i] = res.getIdentifier(NAV_TAB_NAMES[i], "id", pkg)
            }
            if (ids[0] != 0) resolvedIds = ids
        } catch (ignored: Throwable) {
        }
        return ids
    }

    private fun isNight(v: View): Boolean {
        return try {
            (v.resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK) ==
                Configuration.UI_MODE_NIGHT_YES
        } catch (ignored: Throwable) {
            true
        }
    }

    /**
     * The overlay itself. A FrameLayout that OWNS every gesture by
     * consuming DOWN in onTouchEvent (1.17.1): it returns true for
     * ACTION_DOWN, so it becomes the touch target and all later
     * MOVE/UP events come here directly. The 1.17 design tried to let
     * DOWN pass through to the tabs and intercept only on MOVE — that
     * can never work for a sibling overlay (Android only consults
     * onInterceptTouchEvent once per gesture, for the DOWN), so the
     * drag machine was unreachable dead code. Taps are emulated with
     * performClick on UP and long-press is forwarded with
     * performLongClick after the system timeout, since the tab itself
     * never receives DOWN any more. Cosmetic cost: the tab's
     * pressed-state drawable does not show during the touch; the
     * highlight pill still moves on selection.
     */
    private class DragOverlay(private val bar: ViewGroup) : FrameLayout(bar.context) {

        private var downX = 0f
        private var downY = 0f
        private var activePointerId = MotionEvent.INVALID_POINTER_ID
        private var dragging = false
        private var longPressFired = false
        private var lensVisible = false
        private var lensX = 0f
        private var settleAnimator: ValueAnimator? = null

        // Long-press passthrough: if the finger stays down past the
        // system long-press timeout without dragging, the tab under the
        // finger gets its long-press.
        private val longPressRunnable = Runnable {
            try {
                if (!dragging && activePointerId != MotionEvent.INVALID_POINTER_ID) {
                    longPressFired = true
                    DragLensHook.nearestTab(bar, downX)?.performLongClick()
                }
            } catch (ignored: Throwable) {
            }
        }

        private val fillPaint = Paint(Paint.ANTI_ALIAS_FLAG)
        private val strokePaint = Paint(Paint.ANTI_ALIAS_FLAG)

        init {
            // A plain ViewGroup draws nothing by default; this flag is
            // what lets onDraw actually run.
            setWillNotDraw(false)
        }

        override fun onInterceptTouchEvent(ev: MotionEvent): Boolean {
            // 1.17.1: nothing to intercept here. The overlay owns the
            // gesture by consuming DOWN in onTouchEvent, so once it is
            // the touch target this method is never consulted for
            // MOVE/UP. (The 1.17 design tried to intercept on MOVE
            // after a pass-through DOWN — impossible for a sibling
            // overlay: Android consults this exactly once per gesture,
            // for the DOWN, and MOVE/UP then flow to the view that got
            // DOWN. See the class doc.)
            return false
        }

        override fun onTouchEvent(ev: MotionEvent): Boolean {
            // 1.17.1: the overlay MUST own the gesture — a sibling
            // overlay can never intercept one (see the class doc).
            // Returning true for DOWN makes the overlay the touch
            // target, so all later MOVE/UP events come here directly.
            try {
                when (ev.actionMasked) {
                    MotionEvent.ACTION_DOWN -> {
                        cancelSettle()
                        removeCallbacks(longPressRunnable)
                        activePointerId = ev.getPointerId(0)
                        downX = ev.x
                        downY = ev.y
                        dragging = false
                        longPressFired = false
                        postDelayed(
                            longPressRunnable,
                            ViewConfiguration.getLongPressTimeout().toLong()
                        )
                        RdxLog.d("drag DOWN received at (" + downX + "," + downY + ")")
                        return true
                    }
                    MotionEvent.ACTION_MOVE -> {
                        if (activePointerId == MotionEvent.INVALID_POINTER_ID) return true
                        val idx = ev.findPointerIndex(activePointerId)
                        if (idx < 0) return true
                        val dx = ev.getX(idx) - downX
                        val dy = ev.getY(idx) - downY
                        if (!dragging && abs(dx) > dp(DragLensHook.DRAG_THRESHOLD_DP) && abs(dx) > abs(dy)) {
                            if (DragLensHook.tabCenters(bar).size < 2) return true
                            removeCallbacks(longPressRunnable)
                            dragging = true
                            lensVisible = true
                            lensX = clampX(ev.getX(idx))
                            invalidate()
                            RdxLog.d("drag started, lensX=" + lensX)
                            return true
                        }
                        if (dragging) {
                            lensX = clampX(ev.getX(idx))
                            invalidate()
                        }
                        return true
                    }
                    MotionEvent.ACTION_UP -> {
                        removeCallbacks(longPressRunnable)
                        if (activePointerId == MotionEvent.INVALID_POINTER_ID) return true
                        activePointerId = MotionEvent.INVALID_POINTER_ID
                        if (dragging) {
                            dragging = false
                            release(lensX)
                        } else if (!longPressFired) {
                            // It was a tap: the tab never got DOWN (we
                            // own the gesture), so deliver the tap the
                            // same way a real tap ends — performClick
                            // on the tab under the finger.
                            val tapped = DragLensHook.nearestTab(bar, downX)
                            val clicked = tapped?.performClick() ?: false
                            RdxLog.d(
                                "drag tap emulated at x=" + downX +
                                    " performClick=" + clicked
                            )
                        }
                        return true
                    }
                    MotionEvent.ACTION_CANCEL -> {
                        removeCallbacks(longPressRunnable)
                        dragging = false
                        activePointerId = MotionEvent.INVALID_POINTER_ID
                        hideLens()
                        return true
                    }
                }
            } catch (ignored: Throwable) {
            }
            return false
        }

        /** Release: switch to the nearest tab, settle the lens onto it. */
        private fun release(x: Float) {
            var target: View? = null
            var targetCentre = x
            try {
                target = DragLensHook.nearestTab(bar, x)
                if (target != null) {
                    targetCentre = target.left + target.width / 2f
                    // The same path a tap takes — no private API, no
                    // ViewPager call, so the tab's own state machine runs.
                    val clicked = target.performClick()
                    RdxLog.d(
                        "drag release: targetCentre=" + targetCentre +
                            " performClick=" + clicked
                    )
                }
            } catch (ignored: Throwable) {
            }
            if (target == null) {
                // No resolvable target: fall back to doing nothing rather
                // than clicking the wrong thing. The drag just ends.
                RdxLog.d("drag release: no resolvable target at x=" + x)
                hideLens()
                return
            }
            settleLensTo(targetCentre)
        }

        private fun settleLensTo(targetX: Float) {
            try {
                cancelSettle()
                val startX = lensX
                if (abs(targetX - startX) < 1f) {
                    hideLens()
                    return
                }
                lensVisible = true
                val animator = ValueAnimator.ofFloat(startX, targetX)
                animator.duration = DragLensHook.SETTLE_MS
                animator.interpolator = OvershootInterpolator(1.5f)
                animator.addUpdateListener { animation ->
                    lensX = (animation.animatedValue as? Float) ?: targetX
                    invalidate()
                }
                animator.addListener(object : AnimatorListenerAdapter() {
                    override fun onAnimationEnd(animation: Animator) {
                        if (settleAnimator === animation) {
                            settleAnimator = null
                            hideLens()
                        }
                    }

                    override fun onAnimationCancel(animation: Animator) {
                        if (settleAnimator === animation) settleAnimator = null
                    }
                })
                settleAnimator = animator
                animator.start()
            } catch (ignored: Throwable) {
                hideLens()
            }
        }

        private fun cancelSettle() {
            try {
                settleAnimator?.cancel()
            } catch (ignored: Throwable) {
            }
            settleAnimator = null
        }

        private fun hideLens() {
            if (!lensVisible) return
            lensVisible = false
            invalidate()
        }

        private fun clampX(x: Float): Float {
            return max(0f, min(x, width.toFloat()))
        }

        private fun dp(dp: Int): Float {
            return dp * resources.displayMetrics.density
        }

        override fun onDraw(canvas: Canvas) {
            super.onDraw(canvas)
            if (!lensVisible) return
            try {
                val h = height.toFloat()
                if (h <= 0f || width <= 0) return
                // Slight stretch while pulled away from the drag start
                // (up to ~12%), so the lens feels elastic, not rigid.
                val pull = if (width > 0) abs(lensX - downX) / width else 0f
                val stretch = 1f + min(DragLensHook.LENS_STRETCH_MAX, pull * 0.5f)
                val lensW = dp(DragLensHook.LENS_WIDTH_DP) * stretch
                val lensH = h - dp(12)
                if (lensH <= 0f) return
                val radius = lensH / 2f
                val left = (lensX - lensW / 2f).coerceIn(0f, width - lensW)
                val top = (h - lensH) / 2f
                val night = DragLensHook.isNight(this)
                fillPaint.style = Paint.Style.FILL
                fillPaint.color = if (night) Color.argb(46, 255, 255, 255)
                else Color.argb(31, 0, 0, 0)
                strokePaint.style = Paint.Style.STROKE
                strokePaint.strokeWidth = max(1f, dp(1))
                strokePaint.color = if (night) Color.argb(90, 255, 255, 255)
                else Color.argb(48, 0, 0, 0)
                canvas.drawRoundRect(left, top, left + lensW, top + lensH, radius, radius, fillPaint)
                canvas.drawRoundRect(left, top, left + lensW, top + lensH, radius, radius, strokePaint)
            } catch (ignored: Throwable) {
            }
        }
    }
}
