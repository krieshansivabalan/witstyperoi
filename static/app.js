function openModal(id) {
  document.getElementById(id).classList.remove('hidden');
}

function closeModal(id) {
  document.getElementById(id).classList.add('hidden');
}

// Add lead form submission
document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('add-lead-form');
  if (!form) return;

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const data = {};
    fd.forEach((v, k) => { if (v) data[k] = v; });

    fetch('/api/leads', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data),
    })
      .then(r => r.json())
      .then(res => {
        if (res.id) {
          window.location = `/leads/${res.id}`;
        }
      });
  });
});
