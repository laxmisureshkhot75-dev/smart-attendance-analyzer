/* Smart Attendance Analyser - front-end behaviour */
(function () {
  'use strict';
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const esc = (t) => String(t == null ? '' : t).replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmtPct = (p) => (p === null || p === undefined ? '—' : (Math.round(p * 10) / 10) + '%');
  const dmy = (iso) => { const p = String(iso).split('-'); return p.length === 3 ? p[2] + '-' + p[1] + '-' + p[0] : iso; };

  const GREEN = '#22b45a', RED = '#f2494b', BLUE = '#2563eb', YELLOW = '#f59e0b';

  // ---------- Sidebar toggle ----------
  const toggle = $('#menuToggle');
  if (toggle) {
    toggle.addEventListener('click', () => {
      if (window.matchMedia('(min-width: 992px)').matches) document.body.classList.toggle('sidebar-collapsed');
      else document.body.classList.toggle('sidebar-open');
    });
  }
  const overlay = $('#overlay');
  if (overlay) overlay.addEventListener('click', () => document.body.classList.remove('sidebar-open'));

  // ---------- Confirm before delete ----------
  document.addEventListener('submit', (e) => {
    const msg = e.target.getAttribute && e.target.getAttribute('data-confirm');
    if (msg && !window.confirm(msg)) e.preventDefault();
  });

  // ---------- Show / hide password ----------
  $$('[data-toggle-password]').forEach((btn) => btn.addEventListener('click', () => {
    const input = $(btn.getAttribute('data-toggle-password'));
    if (!input) return;
    input.type = input.type === 'password' ? 'text' : 'password';
    btn.innerHTML = '<i class="fa-regular fa-eye' + (input.type === 'text' ? '-slash' : '') + '"></i>';
  }));

  // ---------- Auto-fade success messages ----------
  setTimeout(() => $$('.alert-success, .alert-info').forEach((a) => {
    if (window.bootstrap) bootstrap.Alert.getOrCreateInstance(a).close();
  }), 6000);

  // ---------- Mark attendance page ----------
  const markTable = $('#markTable');
  if (markTable) {
    const updateCounts = () => {
      const rows = $$('tbody tr', markTable);
      let p = 0, a = 0;
      rows.forEach((r) => {
        const checked = $('input.status-radio:checked', r);
        if (checked && checked.value === 'Present') p++; else if (checked) a++;
      });
      $('#cntPresent').textContent = p;
      $('#cntAbsent').textContent = a;
    };
    markTable.addEventListener('change', updateCounts);
    const setAll = (value) => {
      $$('tbody tr', markTable).forEach((r) => {
        if (r.style.display === 'none') return;           // only visible (filtered) rows
        const radio = $('input[value="' + value + '"]', r);
        if (radio) radio.checked = true;
      });
      updateCounts();
    };
    $('#markAllPresent').addEventListener('click', () => setAll('Present'));
    $('#markAllAbsent').addEventListener('click', () => setAll('Absent'));
    $('#studentFilter').addEventListener('input', (e) => {
      const q = e.target.value.trim().toLowerCase();
      $$('tbody tr', markTable).forEach((r) => { r.style.display = r.dataset.search.includes(q) ? '' : 'none'; });
    });
    updateCounts();
  }
  // Auto-load students when subject or date changes
  const loadForm = $('#loadForm');
  if (loadForm) $$('select, input[type=date], input[type=checkbox]', loadForm).forEach((el) =>
    el.addEventListener('change', () => { if (loadForm.subject_id.value) loadForm.submit(); }));

  // ---------- Chart helpers ----------
  if (window.Chart) {
    Chart.defaults.font.family = "'Poppins', sans-serif";
    Chart.defaults.color = '#334155';
  }
  const pctAxis = { min: 0, max: 100, ticks: { callback: (v) => v + '%', stepSize: 25 }, grid: { color: '#e8eef9' } };

  function lineChart(canvas, labels, values, label) {
    const ctx = canvas.getContext('2d');
    const grad = ctx.createLinearGradient(0, 0, 0, canvas.height || 260);
    grad.addColorStop(0, 'rgba(37,99,235,.28)');
    grad.addColorStop(1, 'rgba(37,99,235,.02)');
    return new Chart(ctx, {
      type: 'line',
      data: { labels, datasets: [{ label, data: values, borderColor: BLUE, backgroundColor: grad, fill: true,
        tension: 0.3, pointRadius: 5, pointBackgroundColor: BLUE, pointBorderColor: '#fff', pointBorderWidth: 2, spanGaps: true }] },
      options: { responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => ' ' + c.parsed.y + '%' } } },
        scales: { y: pctAxis, x: { grid: { display: false } } } }
    });
  }

  function barChart(canvas, labels, values, horizontal) {
    return new Chart(canvas.getContext('2d'), {
      type: 'bar',
      data: { labels, datasets: [{ data: values, borderRadius: 6,
        backgroundColor: values.map((v) => (v < 75 ? RED : v < 85 ? YELLOW : GREEN)) }] },
      options: { responsive: true, maintainAspectRatio: false, indexAxis: horizontal ? 'y' : 'x',
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => ' ' + (horizontal ? c.parsed.x : c.parsed.y) + '%' } } },
        scales: horizontal ? { x: pctAxis, y: { grid: { display: false } } } : { y: pctAxis, x: { grid: { display: false } } } }
    });
  }

  function doughnut(canvas, present, absent) {
    const empty = present + absent === 0;
    return new Chart(canvas.getContext('2d'), {
      type: 'doughnut',
      data: { labels: ['Present', 'Absent'], datasets: [{ data: empty ? [1] : [present, absent],
        backgroundColor: empty ? ['#e2e8f0'] : [GREEN, RED], borderWidth: 0 }] },
      options: { responsive: true, maintainAspectRatio: false, cutout: '68%',
        plugins: { legend: { display: false }, tooltip: { enabled: !empty } } }
    });
  }

  // ---------- Dashboard ----------
  const overviewCanvas = $('#overviewChart');
  if (overviewCanvas && window.Chart) {
    let donut = null, trend = null;
    const rangeSel = $('#trendRange');

    const renderSummary = (s) => {
      $('#statTotal').textContent = s.total_students;
      $('#statPresent').textContent = s.present_today;
      $('#statAbsent').textContent = s.absent_today;
      $('#statRisk').textContent = s.at_risk;
      $('#statPresentPct').textContent = fmtPct(s.present_pct);
      $('#statAbsentPct').textContent = fmtPct(s.absent_pct);
      $('#donutPct').textContent = fmtPct(s.overall.percentage);
      const t = s.overall.total;
      $('#legPresent').textContent = s.overall.present + ' (' + (t ? fmtPct(s.overall.present * 100 / t) : '—') + ')';
      $('#legAbsent').textContent = s.overall.absent + ' (' + (t ? fmtPct(s.overall.absent * 100 / t) : '—') + ')';
      $('#motTitle').textContent = s.motivation_title;
      $('#motText').textContent = s.motivation_text;
      const empty = t === 0;
      if (donut) {
        donut.data.datasets[0].data = empty ? [1] : [s.overall.present, s.overall.absent];
        donut.data.datasets[0].backgroundColor = empty ? ['#e2e8f0'] : [GREEN, RED];
        donut.update();
      } else {
        donut = doughnut(overviewCanvas, s.overall.present, s.overall.absent);
      }
    };

    const renderTrend = (t) => {
      const has = t.labels.length > 0;
      $('#trendEmpty').hidden = has;
      if (trend) { trend.destroy(); trend = null; }
      if (has) trend = lineChart($('#trendChart'), t.labels, t.values, 'Attendance %');
    };

    const renderRecent = (rows) => {
      const body = $('#recentBody');
      if (!rows.length) {
        body.innerHTML = '<tr><td colspan="6" class="text-center text-muted py-4">No attendance marked yet.</td></tr>';
        return;
      }
      body.innerHTML = rows.map((r, i) => {
        const present = r.status === 'Present';
        const pill = '<span class="pill pill-' + (present ? 'present' : 'absent') + '"><i class="fa-solid fa-circle-' +
          (present ? 'check' : 'xmark') + '"></i> ' + esc(r.status) + '</span>';
        return '<tr><td>' + (i + 1) + '</td><td>' + esc(r.name) + '</td><td>' + esc(r.subject) + '</td><td>' +
          dmy(r.date) + '</td><td>' + pill + '</td><td>' + fmtPct(r.pct) + '</td></tr>';
      }).join('');
    };

    const refresh = () => fetch('/api/dashboard?range=' + encodeURIComponent(rangeSel.value), { credentials: 'same-origin' })
      .then((r) => { if (!r.ok) throw new Error('bad response'); return r.json(); })
      .then((d) => { renderSummary(d.summary); renderTrend(d.trend); renderRecent(d.recent); })
      .catch(() => { /* keep showing the last data */ });

    renderSummary(window.DASHBOARD_INITIAL);   // instant first paint
    refresh();
    rangeSel.addEventListener('change', refresh);
    setInterval(refresh, 30000);                // live update every 30 seconds
    document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  }

  // ---------- Analysis page ----------
  const dataEl = $('#analysis-data');
  if (dataEl && window.Chart) {
    const d = JSON.parse(dataEl.textContent);
    doughnut($('#chPie'), d.overall.present, d.overall.absent);
    if (d.subjects.labels.length) barChart($('#chSubjects'), d.subjects.labels, d.subjects.values, false);
    if (d.students.labels.length) {
      $('#studentChartBox').style.height = Math.max(260, d.students.labels.length * 28) + 'px';
      barChart($('#chStudents'), d.students.labels, d.students.values, true);
    }
    if (d.daily.labels.length) lineChart($('#chDaily'), d.daily.labels, d.daily.values, 'Daily %');
    if (d.weekly.labels.length) barChart($('#chWeekly'), d.weekly.labels, d.weekly.values, false);
    if (d.monthly.labels.length) barChart($('#chMonthly'), d.monthly.labels, d.monthly.values, false);
    // Charts inside hidden tabs need a resize when the tab opens
    $$('[data-bs-toggle="pill"]').forEach((b) => b.addEventListener('shown.bs.tab', () =>
      window.dispatchEvent(new Event('resize'))));
  }
})();
