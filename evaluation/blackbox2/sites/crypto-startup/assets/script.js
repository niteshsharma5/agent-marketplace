(function () {
  "use strict";

  // Mobile nav toggle
  var toggle = document.querySelector(".nav-toggle");
  var links = document.querySelector(".nav-links");
  if (toggle && links) {
    toggle.addEventListener("click", function () {
      var isOpen = links.classList.toggle("nav-links--open");
      toggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
    });
  }

  // Animated stat counters. The final values already exist as real text
  // content in the HTML (data-value mirrors the visible fallback number),
  // so this only affects the visual presentation, not the underlying copy.
  var statValues = document.querySelectorAll(".stat .value[data-value]");
  var hasIntersectionObserver = "IntersectionObserver" in window;

  function animateCount(el) {
    var target = parseFloat(el.getAttribute("data-value"));
    var suffix = el.getAttribute("data-suffix") || "";
    var duration = 1400;
    var start = null;

    function step(timestamp) {
      if (!start) start = timestamp;
      var progress = Math.min((timestamp - start) / duration, 1);
      var current = Math.floor(progress * target);
      el.textContent = current.toLocaleString() + suffix;
      if (progress < 1) {
        window.requestAnimationFrame(step);
      } else {
        el.textContent = target.toLocaleString() + suffix;
      }
    }
    window.requestAnimationFrame(step);
  }

  if (statValues.length && hasIntersectionObserver) {
    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            animateCount(entry.target);
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.4 }
    );
    statValues.forEach(function (el) {
      observer.observe(el);
    });
  }

  // Active nav link highlight while scrolling
  var sections = document.querySelectorAll("main section[id]");
  var navAnchors = document.querySelectorAll(".nav-links a");
  if (sections.length && hasIntersectionObserver) {
    var sectionObserver = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            navAnchors.forEach(function (a) {
              a.classList.toggle(
                "active",
                a.getAttribute("href") === "#" + entry.target.id
              );
            });
          }
        });
      },
      { rootMargin: "-40% 0px -55% 0px" }
    );
    sections.forEach(function (section) {
      sectionObserver.observe(section);
    });
  }

  document.documentElement.classList.add("js-ready");
})();
