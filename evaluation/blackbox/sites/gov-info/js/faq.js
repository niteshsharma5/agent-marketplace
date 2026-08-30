document.addEventListener('DOMContentLoaded', function () {
  var buttons = document.querySelectorAll('.faq-question');
  buttons.forEach(function (button) {
    button.addEventListener('click', function () {
      var key = button.getAttribute('data-faq');
      var target = document.getElementById('answer-' + key);
      if (target.textContent) {
        return;
      }
      fetch('js/faq-data.json')
        .then(function (response) { return response.json(); })
        .then(function (data) {
          target.textContent = data[key];
        });
    });
  });
});
