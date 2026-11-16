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
 *    the bar's children untouched. It is a ViewGroup that does NOT
 *    intercept on DOWN — the tap reaches the tab underneath normally,
 *    so plain taps, press states and long-press all behave exactly as
 *    stock. Only once the finger has moved horizontally past an 8dp
 *    threshold (and further sideways than vertically) does it
 *    intercept; the framework then sends the tab an ACTION_CANCEL, and
 *    the drag belongs to the overlay. Because the overlay covers the
 *    bar exactly, its touch coordinates ARE the bar's coordinates, so
 *    tab lookup needs no conversion.
 *  - while dragging, a glass lens pill follows the finger's x (with a
 *    small stretch, up to ~12%, the further it is pulled from where
 *    the drag started);
 *  - on release past the midpoint between two tabs it switches to that
 *    tab (a plain performClick on the tab — the same path a tap takes),
 *    and the lens settles onto the tab's centre with a ValueAnimator +
 *    OvershootInterpolator spring, then fades away;
 *  - on release without crossing a midpoint the finger's tab is the
 *    target anyway (nearest tab wins), so a drag always lands on a tab;
 *  - long-press passes through untouched: no movement means no
 *    intercept, so the tab's own long-press fires as stock;
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
            if (tabCenters(bar).size < 2) return // cannot resolve targets: leave taps alone
            if (bar.width <= 0 || bar.height <= 0) return // not laid out yet
            // The decor is the window root (a FrameLayout by
            // construction); absolute positioning via margins is safe
            // there and never disturbs the content layout. rootView is
            // the bar itself while it is not attached to a window yet.
            val decor = bar.rootView as? ViewGroup ?: return
            if (decor === bar) return
            val overlay = DragOverlay(bar)
            overlay.isClickable = false
            overlay.isFocusable = false
            overlay.importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
            positionOverlay(overlay, bar)
            decor.addView(overlay)
            attachedOverlay = overlay
            attachedBarRef = WeakReference(bar)
            bar.setTag(TAG_DRAG_OVERLAY, overlay)
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
     * The overlay itself. A FrameLayout so it can use
     * onInterceptTouchEvent: DOWN passes through to the tabs, and only a
     * real horizontal drag is intercepted (the tab then gets
     * ACTION_CANCEL from the framework, exactly as if the finger had
     * slid off it).
     */
    private class DragOverlay(private val bar: ViewGroup) : FrameLayout(bar.context) {

        private var downX = 0f
        private var downY = 0f
        private var activePointerId = MotionEvent.INVALID_POINTER_ID
        private var dragging = false
        private var lensVisible = false
        private var lensX = 0f
        private var settleAnimator: ValueAnimator? = null

        private val fillPaint = Paint(Paint.ANTI_ALIAS_FLAG)
        private val strokePaint = Paint(Paint.ANTI_ALIAS_FLAG)

        init {
            // A plain ViewGroup draws nothing by default; this flag is
            // what lets onDraw actually run.
            setWillNotDraw(false)
        }

        override fun onInterceptTouchEvent(ev: MotionEvent): Boolean {
            try {
                when (ev.actionMasked) {
                    MotionEvent.ACTION_DOWN -> {
                        cancelSettle()
                        activePointerId = ev.getPointerId(0)
                        downX = ev.x
                        downY = ev.y
                        dragging = false
                        // Do NOT intercept: the tap (and a possible
                        // long-press) belongs to the tab underneath.
                        return false
                    }
                    MotionEvent.ACTION_MOVE -> {
                        if (activePointerId == MotionEvent.INVALID_POINTER_ID) return false
                        val idx = ev.findPointerIndex(activePointerId)
                        if (idx < 0) return false
                        val dx = ev.getX(idx) - downX
                        val dy = ev.getY(idx) - downY
                        if (!dragging && abs(dx) > dp(DragLensHook.DRAG_THRESHOLD_DP) && abs(dx) > abs(dy)) {
                            if (DragLensHook.tabCenters(bar).size < 2) return false
                            dragging = true
                            lensVisible = true
                            lensX = clampX(ev.getX(idx))
                            invalidate()
                            // From here the gesture is ours; the framework
                            // cancels the tab's pressed state for us.
                            return true
                        }
                        if (dragging) {
                            lensX = clampX(ev.getX(idx))
                            invalidate()
                            return true
                        }
                    }
                    MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                        activePointerId = MotionEvent.INVALID_POINTER_ID
                    }
                }
            } catch (ignored: Throwable) {
            }
            return false
        }

        override fun onTouchEvent(ev: MotionEvent): Boolean {
            // Only reached after an intercept — i.e. only while dragging.
            try {
                when (ev.actionMasked) {
                    MotionEvent.ACTION_MOVE -> {
                        if (!dragging) return false
                        val idx = ev.findPointerIndex(activePointerId)
                        if (idx < 0) return true
                        lensX = clampX(ev.getX(idx))
                        invalidate()
                        return true
                    }
                    MotionEvent.ACTION_UP -> {
                        if (!dragging) return false
                        dragging = false
                        activePointerId = MotionEvent.INVALID_POINTER_ID
                        release(lensX)
                        return true
                    }
                    MotionEvent.ACTION_CANCEL -> {
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
                    target.performClick()
                }
            } catch (ignored: Throwable) {
            }
            if (target == null) {
                // No resolvable target: fall back to doing nothing rather
                // than clicking the wrong thing. The tap the drag started
                // from was already cancelled, so this drag just ends.
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
