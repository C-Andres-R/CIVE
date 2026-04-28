// Script de datos dashboard.

(() => {
  const form = document.querySelector('form[data-datos-filter="date-range"]');
  const dashboard = window.datosDashboard;

  if (form) {
    const errorEls = {
      fecha_inicio: form.querySelector('[data-field-error="fecha_inicio"]'),
      fecha_fin: form.querySelector('[data-field-error="fecha_fin"]'),
    };
    let submitAttempted = Object.values(errorEls).some((el) => el && el.textContent.trim());

    // Función para iso today.
    const isoToday = () => {
      const today = new Date();
      return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    };

    // Función para set error.
    const setError = (field, message) => {
      const el = errorEls[field];
      if (el) el.textContent = submitAttempted ? (message || "") : "";
    };

    // Función para validate date range.
    const validateDateRange = () => {
      const fechaInicioInput = form.querySelector('input[name="fecha_inicio"]');
      const fechaFinInput = form.querySelector('input[name="fecha_fin"]');
      const fechaInicio = fechaInicioInput ? fechaInicioInput.value : "";
      const fechaFin = fechaFinInput ? fechaFinInput.value : "";
      const today = isoToday();
      let valid = true;

      if (!fechaInicio) {
        setError("fecha_inicio", "Debes seleccionar la fecha inicial.");
        valid = false;
      } else if (fechaInicio > today) {
        setError("fecha_inicio", "La fecha inicial no puede ser posterior a hoy.");
        valid = false;
      } else {
        setError("fecha_inicio", "");
      }

      if (!fechaFin) {
        setError("fecha_fin", "Debes seleccionar la fecha final.");
        valid = false;
      } else if (fechaFin > today) {
        setError("fecha_fin", "La fecha final no puede ser posterior a hoy.");
        valid = false;
      } else if (fechaInicio && fechaFin < fechaInicio) {
        setError("fecha_fin", "La fecha final no puede ser anterior a la fecha inicial.");
        valid = false;
      } else {
        setError("fecha_fin", "");
      }

      return valid;
    };

    form.querySelectorAll("input").forEach((input) => {
      input.addEventListener("change", validateDateRange);
      input.addEventListener("input", validateDateRange);
    });

    form.addEventListener("submit", (event) => {
      submitAttempted = true;
      if (!validateDateRange()) event.preventDefault();
    });
  }

  if (!dashboard) return;

  const refreshButton = document.getElementById("refreshMonitor");
  const timestampEl = document.getElementById("monitorTimestamp");
  const monitorRows = document.getElementById("monitorRows");

  // Función para refresh monitor.
  async function refreshMonitor() {
    if (!dashboard.monitorUrl || !monitorRows) return;
    if (refreshButton) refreshButton.disabled = true;
    try {
      const response = await fetch(dashboard.monitorUrl, { headers: { "X-Requested-With": "fetch" } });
      const payload = await response.json();
      if (!payload.ok) return;
      const monitoring = payload.monitoring;
      ["citas_hoy", "consultas_hoy", "vacunas_hoy", "analisis_hoy", "ingresos_hoy", "ingresos_mensuales"].forEach((key) => {
        const el = document.querySelector(`[data-monitor="${key}"]`);
        if (el) el.textContent = monitoring[key];
      });
      timestampEl.textContent = `Última actualización: ${monitoring.ultima_actualizacion}`;
      if (monitoring.veterinarios.length) {
        monitorRows.innerHTML = "";
        monitoring.veterinarios.forEach((row) => {
          const tr = document.createElement("tr");
          [row.veterinario, row.consultas, row.vacunas, row.analisis, row.total].forEach((value) => {
            const td = document.createElement("td");
            td.textContent = value;
            tr.appendChild(td);
          });
          monitorRows.appendChild(tr);
        });
      } else {
        monitorRows.innerHTML = `<tr><td colspan="5">Sin actividad registrada hoy.</td></tr>`;
      }
    } finally {
      if (refreshButton) refreshButton.disabled = false;
    }
  }

  let monitorInterval = null;
  // Función para start auto refresh.
  function startAutoRefresh() {
    if (monitorInterval) {
      clearInterval(monitorInterval);
    }
    monitorInterval = window.setInterval(refreshMonitor, 60000);
  }

  if (refreshButton) refreshButton.addEventListener("click", refreshMonitor);
  startAutoRefresh();
})();
