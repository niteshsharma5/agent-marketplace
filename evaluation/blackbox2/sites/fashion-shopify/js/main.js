// Aurelie & Co. -- small progressive-enhancement script.
// The page is fully usable without this file: variant selection uses native
// radio inputs and CSS, and details/summary handles the accordions natively.
// This script only adds a lightweight "add to bag" confirmation.

document.addEventListener('DOMContentLoaded', function () {
  var addToCartForm = document.querySelector('[data-add-to-cart-form]');
  if (!addToCartForm) return;

  var toast = document.getElementById('cart-toast');
  var cartCount = document.getElementById('cart-count');
  var count = 0;

  addToCartForm.addEventListener('submit', function (event) {
    event.preventDefault();

    var sizeInput = addToCartForm.querySelector('input[name="size"]:checked');
    if (!sizeInput) {
      if (toast) {
        toast.textContent = 'Please select a size before adding to your bag.';
        toast.classList.add('show');
      }
      return;
    }

    count += 1;
    if (cartCount) {
      cartCount.textContent = String(count);
    }
    if (toast) {
      var size = sizeInput.value;
      toast.textContent = 'Added to bag — size ' + size + '.';
      toast.classList.add('show');
    }
  });
});
