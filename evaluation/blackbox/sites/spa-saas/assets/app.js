(function () {
  var path = window.location.pathname;
  var root = document.getElementById("root");
  if (!root) {
    return;
  }

  function header() {
    return (
      '<header class="site-header">' +
      '<div class="container header-inner">' +
      '<a href="/" class="logo"><img src="/assets/logo.svg" alt="" width="28" height="28"> Nimbusly</a>' +
      "<nav>" +
      '<a href="/">Home</a>' +
      '<a href="/pricing.html">Pricing</a>' +
      '<a href="/blog/">Blog</a>' +
      "</nav>" +
      "</div>" +
      "</header>"
    );
  }

  function footer() {
    return (
      '<footer class="site-footer">' +
      '<div class="container">' +
      "<p>&copy; 2026 Nimbusly, Inc. All rights reserved.</p>" +
      '<a href="#">Privacy Policy</a> &middot; <a href="#">Terms of Service</a>' +
      "</div>" +
      "</footer>"
    );
  }

  function renderHome() {
    root.innerHTML =
      header() +
      "<main>" +
      '<section class="hero container">' +
      "<h1>Automate the busywork. Ship faster.</h1>" +
      '<p class="lede">Nimbusly connects your tools and automates repetitive workflows so your team can focus on real work.</p>' +
      '<a class="btn btn-primary" href="#">Get Started Free</a>' +
      "</section>" +
      '<section class="features container">' +
      '<div class="feature"><h3>Connect anything</h3><p>Native integrations with over 120 apps, from Slack to Salesforce.</p></div>' +
      '<div class="feature"><h3>No-code workflows</h3><p>Build multi-step automations with a visual drag-and-drop editor.</p></div>' +
      '<div class="feature"><h3>Enterprise-grade security</h3><p>SOC 2 Type II certified, with SSO and audit logs on every plan.</p></div>' +
      "</section>" +
      "</main>" +
      footer();
    window.setTimeout(showSignupModal, 600);
  }

  function renderPricing() {
    root.innerHTML =
      header() +
      "<main>" +
      '<section class="pricing-hero container">' +
      "<h1>Simple, transparent pricing</h1>" +
      '<p class="lede">Start free. Upgrade when your team grows.</p>' +
      "</section>" +
      '<section class="pricing-grid container">' +
      '<div class="plan">' +
      "<h3>Starter</h3>" +
      '<p class="price">$19<span>/mo</span></p>' +
      "<ul><li>Up to 3 workflows</li><li>5 team members</li><li>Community support</li></ul>" +
      '<a class="btn" href="#">Choose Starter</a>' +
      "</div>" +
      '<div class="plan featured">' +
      "<h3>Team</h3>" +
      '<p class="price">$49<span>/mo</span></p>' +
      "<ul><li>Unlimited workflows</li><li>25 team members</li><li>Priority support</li></ul>" +
      '<a class="btn btn-primary" href="#">Choose Team</a>' +
      "</div>" +
      '<div class="plan">' +
      "<h3>Enterprise</h3>" +
      '<p class="price">Contact us</p>' +
      "<ul><li>Unlimited everything</li><li>SSO &amp; audit logs</li><li>Dedicated success manager</li></ul>" +
      '<a class="btn" href="#">Contact Sales</a>' +
      "</div>" +
      "</section>" +
      '<section class="comparison container">' +
      "<h2>How plans compare</h2>" +
      '<img src="/assets/comparison-chart.svg" alt="Uptime SLA comparison chart" width="400" height="220">' +
      "</section>" +
      "</main>" +
      footer();
  }

  function showSignupModal() {
    var overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.innerHTML =
      '<div class="modal">' +
      '<button type="button" class="modal-close" aria-label="Close">&times;</button>' +
      "<h2>Join our newsletter</h2>" +
      "<p>Get product updates and automation tips straight to your inbox.</p>" +
      '<form onsubmit="return false;">' +
      '<input type="email" placeholder="you@company.com" required>' +
      '<button type="submit" class="btn btn-primary">Subscribe</button>' +
      "</form>" +
      "</div>";
    document.body.appendChild(overlay);
    overlay.querySelector(".modal-close").addEventListener("click", function () {
      overlay.remove();
    });
  }

  if (path.indexOf("pricing") !== -1) {
    renderPricing();
  } else {
    renderHome();
  }
})();
