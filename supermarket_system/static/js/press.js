/* A press is answered at once, even when the page it asks for is an ocean
 * away. The server sits far from the shop and every page takes a moment to
 * arrive; without this the button looks dead for that moment and gets pressed
 * again. So the instant a link is followed or a form is sent, a thin bar runs
 * across the top and the page dims a touch: "heard you, it's coming".
 *
 * It decides nothing about layout and changes no behaviour: the link and the
 * form work exactly as they would without it. Coming back with the Back
 * button clears it.
 */
(function () {
  var root = document.documentElement;

  var timer;
  function going() {
    root.classList.add('is-going');
    // A link that only downloads a file never leaves the page; let go.
    clearTimeout(timer);
    timer = setTimeout(function () { root.classList.remove('is-going'); }, 12000);
  }

  document.addEventListener('click', function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey) return;
    var a = e.target.closest && e.target.closest('a[href]');
    if (!a || a.target === '_blank' || a.hasAttribute('download')) return;
    var href = a.getAttribute('href');
    if (!href || href.charAt(0) === '#' || href.indexOf('javascript:') === 0) return;
    if (a.origin && a.origin !== location.origin) return;
    going();
  });

  document.addEventListener('submit', function (e) {
    if (e.defaultPrevented) return;
    var form = e.target;
    // A form that prints or downloads leaves the page where it is.
    if (form.target === '_blank' || form.hasAttribute('data-no-wait')) return;
    going();
  });

  window.addEventListener('pageshow', function () { root.classList.remove('is-going'); });
})();
