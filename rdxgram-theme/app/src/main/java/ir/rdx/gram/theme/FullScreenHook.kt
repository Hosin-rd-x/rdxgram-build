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
 * Full-screen feed for RdxGram 1.13 (on top of the 1.11 capsule fix and
 * 1.12 hardware acceleration).
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
 * Geometry is set by CODE, not XML: the tabBarHeight attribute
 * (0x7f040d3e) has NO value in the resource table, and the pager /
 * container heights are set per-tab by Instagram's own code — so this
 * is a runtime hook in the theme module, same pattern as TabBarHook.
 *
 * Conservative by design: every step is null-checked and wrapped in
 * its own try/catch, so a missing view (or a view Instagram rebuilt
 * mid-swipe) can never crash the app — that step is skipped and the
 * rest still runs. Original paddings / visibilities are saved the
 * first time they are changed, so a future restore can put them back.
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

    // -- geometry: feed under the capsule, nothing over it but the capsule ---

    private fun applyGeometry(a: Activity) {
        val root = a.window?.decorView as? ViewGroup ?: return
        val pkg = a.packageName
        try {
            // The wrapper starts below the status bar (y=48 on the Redroid
            // probe); its top padding is the status inset. Clear it so the
            // header/feed reach y=0 under the transparent status bar.
            val wrapper = findByName(root, a, "layout_container_main_wrapper", pkg)
            if (wrapper != null) clearTopPadding(wrapper)
        } catch (ignored: Throwable) {
        }
        try {
            val container = findByName(root, a, "layout_container_main", pkg)
            if (container != null) {
                clearBottomPadding(container)
                container.clipToPadding = false
            }
            // The pager is what actually ends above the bar (y=1088 on the
            // Redroid probe while the content area runs to y=1184): grow
            // it to fill its container and let its children draw into the
            // padding area, so feed content scrolls UNDER the capsule.
            val pager = findByName(root, a, "swipeable_tab_view_pager", pkg)
            if (pager != null) {
                clearBottomPadding(pager)
                pager.clipToPadding = false
                growToParent(pager)
                // ViewPager2's child is its own RecyclerView; its bottom
                // padding is Instagram's room for the tab bar — same
                // treatment, so the last rows slide under the capsule.
                for (i in 0 until pager.childCount) {
                    try {
                        val child = pager.getChildAt(i) ?: continue
                        if (child.javaClass.name.contains("RecyclerView")) {
                            clearBottomPadding(child)
                            child.clipToPadding = false
                        }
                    } catch (ignored: Throwable) {
                    }
                }
            }
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

    private fun findByName(root: ViewGroup, a: Activity, name: String, pkg: String): View? {
        try {
            val id = a.resources.getIdentifier(name, "id", pkg)
            if (id == 0) return null
            return root.findViewById<View>(id)
        } catch (ignored: Throwable) {
            return null
        }
    }

    private fun savePadding(v: View) {
        if (!savedPaddings.containsKey(v)) {
            savedPaddings[v] = intArrayOf(
                v.paddingLeft, v.paddingTop, v.paddingRight, v.paddingBottom
            )
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

    private fun growToParent(v: View) {
        try {
            val parent = v.parent as? ViewGroup ?: return
            val lp = v.layoutParams ?: return
            // Only grow when the parent is actually taller than the view
            // (per-tab geometry differs — home fills the content area,
            // explore is shorter) and the parent fits on screen, so a
            // mid-layout measurement can never blow the pager up.
            val screenHeight = v.resources.displayMetrics.heightPixels
            if (parent.height > v.height && parent.height <= screenHeight &&
                lp.height != ViewGroup.LayoutParams.MATCH_PARENT
            ) {
                lp.height = ViewGroup.LayoutParams.MATCH_PARENT
                v.layoutParams = lp
            }
        } catch (ignored: Throwable) {
        }
    }

    private fun hideView(v: View) {
        if (v.visibility == View.GONE) return
        if (!savedVisibility.containsKey(v)) savedVisibility[v] = v.visibility
        v.visibility = View.GONE
    }
}
