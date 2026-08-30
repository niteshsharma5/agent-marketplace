// Grandma's Kitchen - newsletter interstitial
// Shows the subscribe modal a short time after each page loads.
// NOTE: intentionally does not remember a prior dismissal (no cookie/localStorage
// check), so it reappears on every page view, including immediately after a
// visitor closes it and clicks through to another recipe.
document.addEventListener('DOMContentLoaded', function () {
  var overlay = document.getElementById('email-modal-overlay');
  if (!overlay) return;

  var showTimer = setTimeout(function () {
    overlay.classList.add('is-visible');
  }, 1500);

  function closeModal() {
    overlay.classList.remove('is-visible');
  }

  var closeBtn = document.getElementById('email-modal-close');
  if (closeBtn) {
    closeBtn.addEventListener('click', closeModal);
  }

  overlay.addEventListener('click', function (event) {
    if (event.target === overlay) {
      closeModal();
    }
  });

  var form = document.getElementById('email-modal-form');
  if (form) {
    form.addEventListener('submit', function (event) {
      event.preventDefault();
      closeModal();
    });
  }
});
