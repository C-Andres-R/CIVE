(() => {
  const forms = document.querySelectorAll('form[data-report-filter]');
  if (!forms.length) return;

  const isoToday = () => {
    const today = new Date();
    return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
  };

  forms.forEach((form) => {
    const mode = form.dataset.reportFilter;
    const errorEls = {
      fecha_inicio: form.querySelector('[data-field-error="fecha_inicio"]'),
      fecha_fin: form.querySelector('[data-field-error="fecha_fin"]'),
      month: form.querySelector('[data-field-error="month"]'),
      year: form.querySelector('[data-field-error="year"]'),
    };
    let submitAttempted = Object.values(errorEls).some((el) => el && el.textContent.trim());

    const setError = (field, message) => {
      const el = errorEls[field];
      if (el) el.textContent = submitAttempted ? (message || '') : '';
    };

    const validateDateRange = () => {
      const fechaInicioInput = form.querySelector('input[name="fecha_inicio"]');
      const fechaFinInput = form.querySelector('input[name="fecha_fin"]');
      const fechaInicio = fechaInicioInput ? fechaInicioInput.value : '';
      const fechaFin = fechaFinInput ? fechaFinInput.value : '';
      const today = isoToday();
      let valid = true;

      if (!fechaInicio) {
        setError('fecha_inicio', 'Debes seleccionar la fecha inicial.');
        valid = false;
      } else if (fechaInicio > today) {
        setError('fecha_inicio', 'La fecha inicial no puede ser posterior a hoy.');
        valid = false;
      } else {
        setError('fecha_inicio', '');
      }

      if (!fechaFin) {
        setError('fecha_fin', 'Debes seleccionar la fecha final.');
        valid = false;
      } else if (fechaFin > today) {
        setError('fecha_fin', 'La fecha final no puede ser posterior a hoy.');
        valid = false;
      } else if (fechaInicio && fechaFin < fechaInicio) {
        setError('fecha_fin', 'La fecha final no puede ser anterior a la fecha inicial.');
        valid = false;
      } else {
        setError('fecha_fin', '');
      }

      return valid;
    };

    const validateMonthYear = () => {
      const monthInput = form.querySelector('[name="month"]');
      const yearInput = form.querySelector('[name="year"]');
      const month = Number(monthInput ? monthInput.value : '');
      const year = Number(yearInput ? yearInput.value : '');
      const currentYear = new Date().getFullYear();
      let valid = true;

      if (!month || month < 1 || month > 12) {
        setError('month', 'Debes seleccionar un mes válido.');
        valid = false;
      } else {
        setError('month', '');
      }

      if (!year || year < 2000 || year > currentYear) {
        setError('year', 'Debes seleccionar un año válido.');
        valid = false;
      } else {
        setError('year', '');
      }

      return valid;
    };

    const validate = () => {
      if (mode === 'month-year') return validateMonthYear();
      return validateDateRange();
    };

    form.querySelectorAll('input, select').forEach((input) => {
      input.addEventListener('change', validate);
      input.addEventListener('input', validate);
    });

    form.addEventListener('submit', (event) => {
      submitAttempted = true;
      if (!validate()) {
        event.preventDefault();
      }
    });
  });
})();
