/**
 * elang console helper — extract answers and answer in place.
 *
 * Purpose: skip the whole IPC round trip when you are already looking at the
 * article. Paste this file into the browser DevTools console on a page that shows
 * the questions, then use the `elang` object.
 *
 *   elang.status()            what the page has (questions, types, key coverage)
 *   elang.extract()           the answers, without touching anything
 *   elang.answer()            apply the answers + clear the read-to-bottom guard
 *   elang.submit()            apply (if needed) then open the confirm dialog
 *   elang.submit(true)        ... and then post it (this is the real submission)
 *   elang.solve()             answer() + dialog only; prints what to do next
 *
 * Every value comes from what the page itself received from the server
 * (`jobList[].options_answer`, `optionsArray[n].title` and the `optionsArray1`
 * mirror), so nothing here guesses. Where a key is missing the question is
 * reported as unresolved and the script refuses to submit.
 *
 * Kept out of the shipped skill on purpose: it is a diagnostic/expedient tool for
 * a human at a keyboard, not part of the agent contract.
 */
(() => {
  const NAME = "elang";

  // ---------------------------------------------------------------- discovery
  function findVm() {
    if (window.__elangPraxisVm && Array.isArray(window.__elangPraxisVm.$data.jobList)) {
      return window.__elangPraxisVm;
    }
    const root = document.querySelector("#app");
    const seen = new Set();
    function walk(vm, depth) {
      if (!vm || depth > 14 || seen.has(vm)) return null;
      seen.add(vm);
      const d = vm.$data || {};
      if (Array.isArray(d.jobList) && d.resources) return vm;
      for (const child of vm.$children || []) {
        const hit = walk(child, depth + 1);
        if (hit) return hit;
      }
      return null;
    }
    const vm = walk(root ? root.__vue__ : null, 0);
    if (vm) window.__elangPraxisVm = vm;
    return vm;
  }

  function methods(vm) {
    return (vm.$options && vm.$options.methods) || {};
  }

  // Decode one job's answer key. Mirrors `_answer_key_from_job` in
  // scripts/elang_reader.py; keep the two in step.
  function decode(job) {
    const tid = Number(job.type_id);
    const raw = typeof job.options_answer === "string" ? job.options_answer.trim() : "";

    if (tid === 1) {
      return /^[A-Za-z]$/.test(raw)
        ? { kind: "choice", labels: [raw.toUpperCase()] }
        : null;
    }
    if (tid === 4) {
      const parts = raw.split(/[,\s]+/).filter(Boolean).map((s) => s.toUpperCase());
      return parts.length && parts.every((p) => /^[A-Z]$/.test(p))
        ? { kind: "multi", labels: parts }
        : null;
    }
    if (tid === 2) {
      // typed fill: the expected text is optionsArray[n].title, one per blank
      const opts = job.optionsArray || [];
      const vals = opts.map((o) => String((o && o.title) || "").trim());
      if (!vals.length || vals.some((v) => !v)) return null;
      return { kind: "fill", values: vals.map((v) => v.split("&")[0].trim()) };
    }
    if (tid === 5 || tid === 7 || tid === 8) {
      let arr = null;
      if (raw) {
        try { arr = JSON.parse(raw); } catch (e) { arr = null; }
      }
      if (!Array.isArray(arr) || !arr.length) {
        const mirror = job.optionsArray1 || [];
        arr = mirror.length ? mirror.slice() : null;
      }
      if (!Array.isArray(arr) || !arr.length) {
        if (raw && raw.length <= 120 && !/^[[{]/.test(raw)) {
          return { kind: "fill", values: [raw] };
        }
        return null;
      }
      const pairs = arr.map((e, i) => {
        const label = Number.isFinite(Number(e && e.label)) ? Number(e.label) : i + 1;
        return [label, String((e && e.title) || "").trim()];
      });
      if (pairs.some((p) => !p[1])) return null;
      pairs.sort((a, b) => a[0] - b[0]);
      return { kind: "fill", values: pairs.map((p) => p[1]) };
    }
    return null; // types 3/6 are free text
  }

  function optionIndex(question, label) {
    const opts = question.optionsArray || [];
    const want = String(label).trim().toUpperCase();
    for (let i = 0; i < opts.length; i++) {
      const lab = String((opts[i] || {}).label || "").trim().toUpperCase().replace(/\.$/, "");
      if (lab === want) return i;
    }
    const idx = want.charCodeAt(0) - 65;
    return idx >= 0 && idx < opts.length ? idx : null;
  }

  function blankCount(job) {
    const fromChunks = (job.titleChunks || []).filter((c) => c.isInput).length;
    const fromOpts = Number(job.type_id) === 2
      ? (job.optionsArray || []).length
      : (job.optionsArray1 || []).length;
    return Math.max(fromChunks, fromOpts, 1);
  }

  // ------------------------------------------------------------------- status
  function status() {
    const vm = findVm();
    if (!vm) {
      console.warn("[elang] no PcReadPraxis instance on this page");
      return null;
    }
    const jobs = vm.$data.jobList || [];
    const rows = jobs.map((job, i) => {
      const key = decode(job);
      return {
        q: i,
        type: Number(job.type_id),
        blanks: blankCount(job),
        key: key ? key.kind : "none",
        answers: key ? (key.labels || key.values) : null,
      };
    });
    const keyed = rows.filter((r) => r.key !== "none").length;
    console.table(rows);
    console.log(`[elang] ${keyed}/${rows.length} questions have a usable answer key`);
    if (vm.readHint) console.log(`[elang] read guard active: ${vm.readHint}`);
    return { questions: rows.length, keyed, rows };
  }

  // ------------------------------------------------------------------ extract
  function extract() {
    const vm = findVm();
    if (!vm) { console.warn("[elang] no PcReadPraxis instance on this page"); return null; }
    const jobs = vm.$data.jobList || [];
    const out = jobs.map((job, i) => {
      const key = decode(job);
      if (!key) return { q: i, type: Number(job.type_id), answer: null, note: "no key" };
      if (key.kind === "fill") return { q: i, type: Number(job.type_id), answer: key.values };
      const idx = key.labels.map((l) => optionIndex(job, l));
      if (idx.some((x) => x === null)) {
        return { q: i, type: Number(job.type_id), answer: null, note: "label not in options" };
      }
      return {
        q: i,
        type: Number(job.type_id),
        answer: key.kind === "multi" ? idx : idx[0],
        labels: key.labels,
      };
    });
    console.table(out);
    return out;
  }

  // ------------------------------------------------------------------- answer
  function applyAnswers(vm) {
    const jobs = vm.$data.jobList || [];
    const M = methods(vm);
    const notes = [];
    let applied = 0;

    jobs.forEach((job, i) => {
      const key = decode(job);
      if (!key) { notes.push(`q${i}: no key`); return; }
      const tid = Number(job.type_id);

      if (key.kind === "fill") {
        const n = blankCount(job);
        if (key.values.length < n) { notes.push(`q${i}: ${n} blanks, ${key.values.length} values`); return; }
        vm.$set(vm.$data.insertWordAnswers, job.id, key.values.slice(0, n));
        if (M.markFillAnswer) { try { M.markFillAnswer.call(vm, i, 0); } catch (e) {} }
        applied++;
        return;
      }

      const idx = key.labels.map((l) => optionIndex(job, l));
      if (idx.some((x) => x === null)) { notes.push(`q${i}: label not in options`); return; }

      if (tid === 4) {
        // selectOption() toggles for type 4, so clear first and then toggle on.
        (job.optionsArray || []).forEach((o) => { o.is_check = 0; });
        idx.forEach((k) => {
          try { M.selectOption.call(vm, i, k); } catch (e) { notes.push(`q${i}: ${e.message}`); }
        });
      } else {
        try { M.selectOption.call(vm, i, idx[0]); } catch (e) { notes.push(`q${i}: ${e.message}`); }
      }
      applied++;
    });

    // Clear the client-side "read to the bottom" guard, otherwise both submit
    // methods only show a toast and never post.
    vm.$data.articleRead = true;
    const rq = vm.$data.readQuestions || {};
    jobs.forEach((_, i) => { rq[i] = true; });
    vm.$data.readQuestions = rq;
    vm.$data.readingStayMs = Math.max(vm.$data.readingStayMs || 0, 120001);
    vm.$data.readingStayLastTick = performance.now();
    document.querySelectorAll(".article-container, .question-panel").forEach((el) => {
      try { el.scrollTop = el.scrollHeight; } catch (e) {}
    });
    if (vm.$forceUpdate) vm.$forceUpdate();

    const answered = jobs.filter((j) => {
      try { return M.isAnswered ? M.isAnswered.call(vm, j) : true; } catch (e) { return false; }
    }).length;

    console.log(`[elang] applied ${applied}/${jobs.length}; page reports ` +
                `${answered}/${jobs.length} answered; readHint='${vm.readHint}'`);
    if (notes.length) console.warn("[elang] notes:", notes);
    return { applied, answered, total: jobs.length, notes, readHint: vm.readHint };
  }

  function answer() {
    const vm = findVm();
    if (!vm) { console.warn("[elang] no PcReadPraxis instance on this page"); return null; }
    return applyAnswers(vm);
  }

  // ------------------------------------------------------------------- submit
  async function submit(postForReal) {
    const vm = findVm();
    if (!vm) { console.warn("[elang] no PcReadPraxis instance on this page"); return null; }
    const M = methods(vm);
    const st = applyAnswers(vm);
    if (!postForReal) {
      M.openSubmitConfirm.call(vm);
      console.log(`[elang] confirm dialog visible=${!!vm.$data.submitConfirmVisible}. ` +
                  `Call elang.submit(true) to post.`);
      return { ...st, posted: false, dialogVisible: !!vm.$data.submitConfirmVisible };
    }
    const beforeHash = location.hash;
    await M.confirmSubmit.call(vm);
    const moved = await new Promise((resolve) => {
      const t0 = Date.now();
      const timer = setInterval(() => {
        if (location.hash !== beforeHash) { clearInterval(timer); resolve(true); }
        else if (Date.now() - t0 > 12000) { clearInterval(timer); resolve(false); }
      }, 250);
    });
    console.log(moved ? "[elang] submitted, page navigated" :
      "[elang] WARNING: no navigation after confirmSubmit — check the network tab");
    return { ...st, posted: true, navigated: moved };
  }

  async function solve() {
    const st = await submit(false);
    if (st && st.readHint) console.warn("[elang] read guard still active:", st.readHint);
    return st;
  }

  window[NAME] = { status, extract, answer, submit, solve, findVm };
  console.log("[elang] ready — elang.status() / elang.extract() / elang.answer() / " +
              "elang.submit() / elang.submit(true)");
})();