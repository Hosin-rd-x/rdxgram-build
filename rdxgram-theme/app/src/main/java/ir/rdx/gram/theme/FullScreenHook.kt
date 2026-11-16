package ir.rdx.gram.theme

import android.app.Activity
import android.graphics.Color
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
            attachTopScrim(a)
        } catch (ignored: Throwable) {
        }
    }

    /**
     * The very light top veil: a non-touchable gradient laid over the
     * content at the top of the decor (drawn above the feed/header, below
     * the system status icons, which live in their own window). Black
     * ~15% at the very top fading to transparent — barely there, only
     * enough to keep the status icons readable over a bright photo.
     * This is a scrim, NOT a blur — see the class doc.
     */
    private fun attachTopScrim(a: Activity) {
        val decor = a.window?.decorView as? ViewGroup ?: return
        val existing = decor.getTag(TAG_TOP_SCRIM) as? View
        if (existing != null && existing.parent === decor) return
        val scrimHeight = statusBarHeight(a) + dp(a, 16)
        val scrim = View(a)
        val gradient = GradientDrawable(
            GradientDrawable.Orientation.TOP_BOTTOM,
            intArrayOf(
                Color.argb(38, 0, 0, 0), // ~15% black at the very top
                Color.argb(20, 0, 0, 0), // ~8% mid-way
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
            growFeed(a, root, pkg)
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
