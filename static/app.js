/* Workout Logger (Milestone #1) - Frontend
   Vanilla JS + Fetch. No build tools.
*/

function $(sel, root = document) {
  return root.querySelector(sel);
}

function $all(sel, root = document) {
  return Array.from(root.querySelectorAll(sel));
}

function showToast(message, { ms = 2200 } = {}) {
  const toast = $("#toast");
  if (!toast) return;
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => { toast.hidden = true; }, ms);
}

async function fetchJson(url, options = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options
  });
  let data = null;
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) {
    const msg = (data && (data.error || (data.errors && data.errors.join("\n")))) || `Request failed (${res.status})`;
    const err = new Error(msg);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

function setToggleHandlers() {
  // Generic show/hide for any [data-toggle="id"] button controlling #id
  $all("[data-toggle]").forEach(btn => {
    btn.addEventListener("click", () => {
      const id = btn.getAttribute("data-toggle");
      const target = document.getElementById(id);
      if (!target) return;
      const isHidden = target.hasAttribute("hidden");
      if (isHidden) {
        target.removeAttribute("hidden");
        btn.setAttribute("aria-expanded", "true");
      } else {
        target.setAttribute("hidden", "");
        btn.setAttribute("aria-expanded", "false");
      }
    });
  });
}

function renderErrors(errors) {
  const box = $("#form-errors");
  if (!box) return;
  if (!errors || errors.length === 0) {
    box.hidden = true;
    box.innerHTML = "";
    return;
  }
  box.hidden = false;
  box.innerHTML = `
    <strong>Please fix the following:</strong>
    <ul>${errors.map(e => `<li>${escapeHtml(e)}</li>`).join("")}</ul>
  `;
}

function escapeHtml(s) {
  return String(s).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}

// ------------------------------------------------------
// History page
// ------------------------------------------------------

async function loadHistory() {
  const listEl = $("#workout-list");
  const emptyEl = $("#empty-state");
  const timingEl = $("#history-timing");
  if (!listEl || !emptyEl) return;

  listEl.innerHTML = `<div class="muted">Loading…</div>`;
  try {
    const data = await fetchJson("/api/workouts");
    const workouts = data.workouts || [];
    if (timingEl) timingEl.textContent = `Loaded in ${data.timing_ms} ms`;

    if (workouts.length === 0) {
      listEl.innerHTML = "";
      emptyEl.hidden = false;
      return;
    }

    emptyEl.hidden = true;
    listEl.innerHTML = workouts.map(w => {
      const title = (w.title || "").trim();
      const displayTitle = title ? title : "Workout";
      return `
        <div class="card" role="article">
          <h3>
            <a href="/workout/${w.id}" aria-label="Open workout details">
              ${escapeHtml(displayTitle)} — ${escapeHtml(w.workout_date)}
            </a>
          </h3>
          <div class="meta">
            <span>${w.exercise_count} exercise(s)</span>
            <span>${w.set_count} set(s)</span>
          </div>
        </div>
      `;
    }).join("");
  } catch (e) {
    listEl.innerHTML = `<div class="errors"><strong>Error:</strong> ${escapeHtml(e.message)}</div>`;
  }
}

async function seedData() {
  try {
    await fetchJson("/api/debug/seed", { method: "POST", body: JSON.stringify({ count: 200 }) });
    showToast("Created 200 sample workouts.");
    await loadHistory();
  } catch (e) {
    showToast(`Seed failed: ${e.message}`, { ms: 3000 });
  }
}

// ------------------------------------------------------
// Workout details page
// ------------------------------------------------------

function renderWorkoutDetails(workout) {
  const el = $("#workout-details");
  if (!el) return;

  const title = (workout.title || "").trim() || "Workout";
  el.innerHTML = `
    <h3>${escapeHtml(title)} — ${escapeHtml(workout.workout_date)}</h3>
    <div class="muted">Last updated: ${escapeHtml(workout.updated_at || "")}</div>
    <div class="exercise-blocks">
      ${(workout.exercises || []).map(ex => `
        <div class="exercise-block">
          <strong>${escapeHtml(ex.name)}</strong>
          <table>
            <thead><tr><th>Set</th><th>Reps</th><th>Weight</th></tr></thead>
            <tbody>
              ${(ex.sets || []).map(s => `
                <tr>
                  <td>${escapeHtml(s.set_number)}</td>
                  <td>${escapeHtml(s.reps)}</td>
                  <td>${escapeHtml(s.weight)}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      `).join("")}
    </div>
  `;
}

async function loadWorkoutDetails(workoutId) {
  const el = $("#workout-details");
  if (!el) return;
  el.innerHTML = `<div class="muted">Loading…</div>`;
  const data = await fetchJson(`/api/workouts/${workoutId}`);
  renderWorkoutDetails(data.workout);
}

async function deleteWorkout(workoutId) {
  // IH#8: encourage mindful tinkering (confirm destructive action)
  const ok = confirm("Delete this workout permanently? This cannot be undone.");
  if (!ok) return;

  await fetchJson(`/api/workouts/${workoutId}`, { method: "DELETE" });
  showToast("Workout deleted.");
  window.location.href = "/";
}

// ------------------------------------------------------
// Workout form (create/edit)
// ------------------------------------------------------

function todayIso() {
  const d = new Date();
  const pad = n => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

// Client-side state for the form
function createEmptyState() {
  return {
    workout_date: todayIso(),
    title: "",
    exercises: []
  };
}

function addExercise(state, name) {
  const trimmed = String(name || "").trim();
  if (!trimmed) return false;
  state.exercises.push({ name: trimmed, sets: [] });
  return true;
}

function addSetToExercise(state, exIndex, reps, weight) {
  const ex = state.exercises[exIndex];
  if (!ex) return { ok: false, error: "Exercise not found." };

  const repsInt = Number.parseInt(reps, 10);
  const weightNum = Number.parseFloat(weight);

  // Issue #11 validation
  if (!Number.isFinite(repsInt) || repsInt < 1) {
    return { ok: false, error: "Reps must be at least 1." };
  }
  if (!Number.isFinite(weightNum) || weightNum < 0) {
    return { ok: false, error: "Weight must be 0 or more." };
  }

  ex.sets.push({ reps: repsInt, weight: weightNum });
  return { ok: true };
}

// Undo = remove the last set in the entire workout (Issue #11 NFR)
function undoLastSet(state) {
  for (let i = state.exercises.length - 1; i >= 0; i--) {
    const sets = state.exercises[i].sets;
    if (sets.length > 0) {
      sets.pop();
      return true;
    }
  }
  return false;
}

function removeExercise(state, exIndex) {
  state.exercises.splice(exIndex, 1);
}

// IH#8: require confirmation for destructive edit (deleting a set)
function removeSetWithConfirm(state, exIndex, setIndex) {
  const ex = state.exercises[exIndex];
  if (!ex) return false;
  const ok = confirm("Remove this set? This will apply when you Save Changes.");
  if (!ok) return false;
  ex.sets.splice(setIndex, 1);
  return true;
}

function validateStateForSave(state) {
  const errors = [];
  if (!state.workout_date) errors.push("Workout date is required.");

  if (!state.exercises || state.exercises.length === 0) {
    errors.push("At least one exercise is required.");
    return errors;
  }

  state.exercises.forEach((ex, i) => {
    if (!String(ex.name || "").trim()) errors.push(`Exercise #${i + 1}: name is required.`);
    if (!ex.sets || ex.sets.length === 0) errors.push(`Exercise '${ex.name || i + 1}': add at least one set.`);
    (ex.sets || []).forEach((s, j) => {
      if (!(Number.isFinite(s.reps) && s.reps >= 1)) errors.push(`Exercise '${ex.name}' set #${j + 1}: reps must be >= 1.`);
      if (!(Number.isFinite(s.weight) && s.weight >= 0)) errors.push(`Exercise '${ex.name}' set #${j + 1}: weight must be >= 0.`);
    });
  });

  return errors;
}

function renderForm(state) {
  const list = $("#exercise-list");
  if (!list) return;

  if (state.exercises.length === 0) {
    list.innerHTML = `<div class="muted">No exercises yet. Add one above.</div>`;
    return;
  }

  list.innerHTML = state.exercises.map((ex, exIndex) => {
    const setsHtml = (ex.sets || []).map((s, setIndex) => `
      <div class="row">
        <div class="muted">Set ${setIndex + 1}:</div>
        <div><strong>${escapeHtml(s.reps)}</strong> reps</div>
        <div><strong>${escapeHtml(s.weight)}</strong> weight</div>
        <button class="icon-button" type="button"
                data-action="remove-set"
                data-ex="${exIndex}" data-set="${setIndex}"
                aria-label="Remove set ${setIndex + 1}">
          Remove
        </button>
      </div>
    `).join("");

    return `
      <div class="exercise" data-ex="${exIndex}">
        <div class="exercise-header">
          <div class="exercise-name">${escapeHtml(ex.name)}</div>
          <button class="icon-button" type="button" data-action="remove-exercise" data-ex="${exIndex}">
            Remove exercise
          </button>
        </div>

        <div class="sets">
          ${setsHtml || `<div class="muted">No sets yet. Add one below.</div>`}

          <div class="set-row" aria-label="Add set for ${escapeHtml(ex.name)}">
            <label>
              <div class="small">Reps (≥ 1)</div>
              <input type="number" min="1" step="1" inputmode="numeric"
                     data-field="reps" data-ex="${exIndex}" placeholder="e.g., 5" />
            </label>

            <label>
              <div class="small">Weight (≥ 0)</div>
              <input type="number" min="0" step="0.5" inputmode="decimal"
                     data-field="weight" data-ex="${exIndex}" placeholder="e.g., 135" />
            </label>

            <!-- IH#7: offer alternative approach (button click) -->
            <button class="button" type="button" data-action="add-set" data-ex="${exIndex}">
              + Set
            </button>
          </div>

          <div class="muted">
            Tip: Press Enter in either field to add the set.
          </div>
        </div>
      </div>
    `;
  }).join("");

  // Wire event handlers for dynamic content
  $all("[data-action='remove-exercise']", list).forEach(btn => {
    btn.addEventListener("click", () => {
      const exIndex = Number(btn.getAttribute("data-ex"));
      // Removing an exercise is a destructive edit but within the unsaved draft; still confirm once.
      const ok = confirm("Remove this exercise from the workout draft?");
      if (!ok) return;
      removeExercise(state, exIndex);
      markDirty();
      renderForm(state);
    });
  });

  $all("[data-action='add-set']", list).forEach(btn => {
    btn.addEventListener("click", () => {
      const exIndex = Number(btn.getAttribute("data-ex"));
      const reps = $(`input[data-field="reps"][data-ex="${exIndex}"]`, list)?.value;
      const weight = $(`input[data-field="weight"][data-ex="${exIndex}"]`, list)?.value;
      const result = addSetToExercise(state, exIndex, reps, weight);
      if (!result.ok) {
        showToast(result.error, { ms: 3000 });
        return;
      }
      markDirty();
      renderForm(state);
    });
  });

  // IH#7: Add set by pressing Enter
  $all("input[data-field='reps'], input[data-field='weight']", list).forEach(inp => {
    inp.addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      e.preventDefault();
      const exIndex = Number(inp.getAttribute("data-ex"));
      const reps = $(`input[data-field="reps"][data-ex="${exIndex}"]`, list)?.value;
      const weight = $(`input[data-field="weight"][data-ex="${exIndex}"]`, list)?.value;
      const result = addSetToExercise(state, exIndex, reps, weight);
      if (!result.ok) {
        showToast(result.error, { ms: 3000 });
        return;
      }
      markDirty();
      renderForm(state);
    });
  });

  $all("[data-action='remove-set']", list).forEach(btn => {
    btn.addEventListener("click", () => {
      const exIndex = Number(btn.getAttribute("data-ex"));
      const setIndex = Number(btn.getAttribute("data-set"));
      // Issue #13 NFR: destructive edits require a single confirmation
      const removed = removeSetWithConfirm(state, exIndex, setIndex);
      if (removed) {
        markDirty();
        renderForm(state);
      }
    });
  });
}

let _dirty = false;
function markDirty() { _dirty = true; }
function clearDirty() { _dirty = false; }

function attachUnsavedWarning() {
  // IH#8: warn before losing progress
  window.addEventListener("beforeunload", (e) => {
    if (!_dirty) return;
    e.preventDefault();
    e.returnValue = "";
  });
}

function attachCancelLink() {
  const link = $("#cancel-link");
  if (!link) return;
  link.addEventListener("click", (e) => {
    if (!_dirty) return;
    const ok = confirm("Discard your unsaved changes?");
    if (!ok) e.preventDefault();
  });
}

async function setupWorkoutForm(mode, workoutId) {
  const dateEl = $("#workout-date");
  const titleEl = $("#workout-title");
  const newExerciseEl = $("#new-exercise-name");
  const addExerciseBtn = $("#add-exercise");
  const undoBtn = $("#undo-last-set");
  const saveBtn = $("#save-workout");

  const state = createEmptyState();

  // Populate if edit mode
  if (mode === "edit" && workoutId) {
    const data = await fetchJson(`/api/workouts/${workoutId}`);
    const w = data.workout;
    state.workout_date = w.workout_date;
    state.title = w.title || "";
    state.exercises = (w.exercises || []).map(ex => ({
      name: ex.name,
      sets: (ex.sets || []).map(s => ({ reps: Number(s.reps), weight: Number(s.weight) }))
    }));
  }

  if (dateEl) dateEl.value = state.workout_date;
  if (titleEl) titleEl.value = state.title;

  dateEl?.addEventListener("change", () => { state.workout_date = dateEl.value; markDirty(); });
  titleEl?.addEventListener("input", () => { state.title = titleEl.value; markDirty(); });

  function tryAddExercise() {
    const ok = addExercise(state, newExerciseEl.value);
    if (!ok) {
      showToast("Enter an exercise name first.", { ms: 2500 });
      return;
    }
    newExerciseEl.value = "";
    markDirty();
    renderForm(state);
  }

  addExerciseBtn?.addEventListener("click", tryAddExercise);

  // IH#7: alternate approach to add exercise = Enter key
  newExerciseEl?.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    tryAddExercise();
  });

  undoBtn?.addEventListener("click", () => {
    const ok = undoLastSet(state);
    if (!ok) {
      showToast("Nothing to undo yet.", { ms: 2000 });
      return;
    }
    markDirty();
    renderForm(state);
    showToast("Last set removed.");
  });

  saveBtn?.addEventListener("click", async () => {
    renderErrors([]);
    const errors = validateStateForSave(state);

    // Issue #11: "Given user attempts to save with no exercises, show error and do not save"
    if (errors.length > 0) {
      renderErrors(errors);
      showToast("Fix the errors before saving.", { ms: 2500 });
      return;
    }

    const payload = {
      workout_date: state.workout_date,
      title: state.title || null,
      exercises: state.exercises.map(ex => ({
        name: ex.name,
        sets: ex.sets.map(s => ({ reps: s.reps, weight: s.weight }))
      }))
    };

    try {
      if (mode === "create") {
        const res = await fetchJson("/api/workouts", { method: "POST", body: JSON.stringify(payload) });
        clearDirty();
        showToast("Workout saved.");
        window.location.href = `/workout/${res.workout_id}`;
      } else {
        await fetchJson(`/api/workouts/${workoutId}`, { method: "PUT", body: JSON.stringify(payload) });
        clearDirty();
        showToast("Changes saved.");
        window.location.href = `/workout/${workoutId}`;
      }
    } catch (e) {
      // Server-side validation errors
      const errs = (e.data && e.data.errors) ? e.data.errors : [e.message];
      renderErrors(errs);
      showToast("Save failed.", { ms: 2500 });
    }
  });

  attachUnsavedWarning();
  attachCancelLink();
  renderForm(state);
}

// ------------------------------------------------------
// Boot
// ------------------------------------------------------

document.addEventListener("DOMContentLoaded", async () => {
  setToggleHandlers();

  const page = window.__PAGE__?.name;

  if (page === "history") {
    $("#refresh-history")?.addEventListener("click", loadHistory);
    $("#seed-data")?.addEventListener("click", seedData);
    await loadHistory();
  }

  if (page === "workout_view") {
    const workoutId = window.__PAGE__.workoutId;
    await loadWorkoutDetails(workoutId);
    $("#delete-workout")?.addEventListener("click", async () => {
      try {
        await deleteWorkout(workoutId);
      } catch (e) {
        showToast(`Delete failed: ${e.message}`, { ms: 3000 });
      }
    });
  }

  if (page === "workout_form") {
    const { mode, workoutId } = window.__PAGE__;
    try {
      await setupWorkoutForm(mode, workoutId);
    } catch (e) {
      renderErrors([e.message]);
    }
  }
});
