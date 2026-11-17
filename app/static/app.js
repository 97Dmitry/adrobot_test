"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
let current = null;
let working = false;
let disabledControls = [];

function setWorking(value) {
  working = value;
  if (value) {
    disabledControls = [
      ...document.querySelectorAll("button,input,select"),
    ].map((element) => [element, element.disabled]);
    for (const [element] of disabledControls) element.disabled = true;
  } else {
    for (const [element, disabled] of disabledControls)
      if (element.isConnected) element.disabled = disabled;
    disabledControls = [];
  }
}

function node(tag, attrs = {}, ...children) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") element.className = value;
    else if (key === "text") element.textContent = value;
    else if (key.startsWith("on"))
      element.addEventListener(key.slice(2), value);
    else if (key in element && key !== "list") element[key] = value;
    else element.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children) {
    if (child !== undefined && child !== null) element.append(child);
  }
  return element;
}

async function api(path, method = "GET", body, headers = {}) {
  const options = {
    method,
    headers: { "Content-Type": "application/json", ...headers },
  };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(`/api${path}`, options);
  } catch {
    throw new Error(
      "Нет связи с приложением. Проверьте, что сервер запущен. Не повторяйте создание с новым ключом до сверки результата.",
    );
  }
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error(
      `Сервер вернул неожиданный ответ (HTTP ${response.status}).`,
    );
  }
  if (!response.ok) {
    const failure = data.error || {};
    let message = failure.message || `Ошибка HTTP ${response.status}`;
    if (Array.isArray(failure.fields)) {
      message +=
        " " +
        failure.fields
          .map((d) => `${d.loc.join(".")}: ${d.message}`)
          .join("; ");
    } else if (failure.details?.campaign_id) {
      message += ` Кампания #${failure.details.campaign_id}.`;
    }
    const error = new Error(message);
    error.status = response.status;
    error.code = failure.code;
    throw error;
  }
  return data;
}

function message(text, success = false) {
  const element = $("#message");
  element.textContent = text;
  element.classList.toggle("success", success);
  element.hidden = !text;
}

function readStored(key) {
  try {
    return JSON.parse(localStorage.getItem(key));
  } catch {
    return null;
  }
}

function store(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* DB remains authoritative. */
  }
}

function numericID(input) {
  const value = input.value.trim();
  if (!/^[1-9]\d*$/.test(value) || !Number.isSafeInteger(Number(value))) {
    throw new Error(
      "Выберите вариант из списка или введите положительный числовой ID.",
    );
  }
  return Number(value);
}

function comparableCreation(body) {
  const prefix = "test_tsybizov_";
  const name = body.name.trim();
  return JSON.stringify([
    name.startsWith(prefix) ? name : prefix + name,
    [...new Set(body.countries.map((code) => code.trim().toUpperCase()))],
    body.offer_id,
    body.domain_id,
    body.group_id,
    body.traffic_source_id,
  ]);
}

function autocomplete(input, list, hint, resource) {
  let timer;
  let sequence = 0;
  input.addEventListener("input", () => {
    clearTimeout(timer);
    const request = ++sequence;
    const query = input.value.trim();
    list.replaceChildren();
    if (!query) {
      hint.textContent = "Введите ID или название";
      return;
    }
    hint.textContent = "Поиск…";
    timer = setTimeout(async () => {
      try {
        const items = await api(`/${resource}?q=${encodeURIComponent(query)}`);
        if (request !== sequence || !input.isConnected) return;
        list.replaceChildren(
          ...items.map((item) =>
            node("option", { value: String(item.id), label: item.name }),
          ),
        );
        const exact = items.find((item) => String(item.id) === query);
        hint.textContent = exact
          ? exact.name
          : items.length
            ? `Найдено: ${items.length}. Выберите вариант из списка.`
            : "Ничего не найдено";
      } catch (error) {
        if (request === sequence && input.isConnected)
          hint.textContent = error.message;
      }
    }, 250);
  });
}

async function connect() {
  $("#retry-connection").hidden = true;
  $("#connection").textContent = "Подключение к Keitaro…";
  try {
    await api("/health");
    const values = await api("/catalogs");
    for (const [id, key] of [
      ["domain", "domains"],
      ["group", "groups"],
      ["source", "traffic_sources"],
    ]) {
      const select = $(`#${id}`);
      select.replaceChildren(
        ...values[key].map((item) =>
          node("option", { value: String(item.id), text: item.name }),
        ),
      );
      const defaults = values[key].find((item) => item.name === "FORTESTS");
      if (defaults) select.value = String(defaults.id);
    }
    $("#creator-fields").disabled = Object.values(values).some(
      (items) => !items.length,
    );
    $("#connection").className = "connection ready";
    $("#connection").textContent = "Keitaro подключён";
    if ($("#creator-fields").disabled)
      message(
        "В Keitaro не хватает домена, группы кампаний или источника. Добавьте их в трекере и повторите подключение.",
      );
  } catch (error) {
    $("#connection").className = "connection failed";
    $("#connection").textContent = "Keitaro недоступен";
    $("#retry-connection").hidden = false;
    message(error.message);
  }
}

function render() {
  $("#empty").hidden = !!current;
  $("#campaign-workspace").hidden = !current;
  if (!current) return;
  $("#campaign-title").textContent = current.name;
  $("#campaign-meta").textContent =
    `Кампания #${current.id} · ${current.state === "active" ? "Активна" : current.state === "disabled" ? "Выключена" : current.state}`;
  $("#tracking-url").textContent = current.tracking_url || "Ссылка не задана";
  $("#campaign-search").value = current.id;
  const dirty = current.streams.some(
    (stream) => stream.dirty || stream.pending,
  );
  $("#sync").disabled = dirty || working;
  $("#sync-hint").textContent = dirty
    ? "Есть черновик. Перед синхронизацией опубликуйте или отмените изменения."
    : current.synced_at
      ? `Последняя загрузка из Keitaro: ${new Date(current.synced_at + "Z").toLocaleString("ru-RU")}`
      : "Потоки ещё не загружены из Keitaro.";
  $("#streams").replaceChildren(...current.streams.map(renderStream));
  if (!current.streams.length)
    $("#streams").append(
      node("p", {
        class: "empty-stream",
        text: "В кампании пока нет потоков. Нажмите «Синхронизировать с Keitaro».",
      }),
    );
}

function button(text, className, onclick, disabled = false) {
  return node("button", {
    type: "button",
    class: className,
    text,
    onclick,
    disabled,
  });
}

function renderStream(stream) {
  const status = stream.missing
    ? "Недоступен"
    : stream.pending
      ? "Нужна сверка"
      : stream.dirty
        ? "Не опубликован"
        : stream.editable
          ? "Опубликован"
          : "Без офферов";
  const statusClass = stream.missing
    ? "missing"
    : stream.pending
      ? "pending"
      : stream.dirty
        ? "draft"
        : "";
  const card = node("article", {
    id: `stream-${stream.id}`,
    class: `stream${stream.dirty ? " dirty" : ""}${stream.missing ? " missing" : ""}`,
    "aria-label": `Поток ${stream.name}`,
  });
  card.append(
    node(
      "div",
      { class: "stream-heading" },
      node(
        "div",
        {},
        node("h3", { text: stream.name }),
        node("p", { class: "stream-id", text: `Поток #${stream.id}` }),
      ),
      node("span", { class: `badge ${statusClass}`, text: status }),
    ),
  );
  if (!stream.offers.length) {
    card.append(
      node("p", {
        class: "empty-stream",
        text: "В этом потоке нет офферов. Его фильтры и перенаправления управляются в Keitaro.",
      }),
    );
  } else {
    const table = node(
      "table",
      {},
      node(
        "thead",
        {},
        node(
          "tr",
          {},
          ...["Оффер", "Доля", "Закрепление веса", "Действие"].map((text) =>
            node("th", { scope: "col", text }),
          ),
        ),
      ),
    );
    const tbody = node("tbody");
    for (const offer of stream.offers) {
      const tr = node("tr", {
        "data-offer-id": offer.offer_id,
        class: offer.active ? "" : "archived",
      });
      tr.append(
        node(
          "td",
          { class: "offer-title" },
          node("div", { class: "offer-id", text: `#${offer.offer_id}` }),
          node("div", { text: offer.name }),
          offer.archived
            ? node("span", {
                class: "hint",
                text: offer.ever_published ? "В архиве" : "Не опубликован",
              })
            : null,
        ),
      );
      tr.append(
        node(
          "td",
          { class: "weight" },
          String(offer.share),
          node("span", { text: "%" }),
        ),
      );
      const weight = node("input", {
        type: "number",
        min: 0,
        max: 100,
        step: 1,
        value: offer.pin ?? offer.share,
        "aria-label": `Закреплённый вес оффера ${offer.offer_id}`,
        disabled: !offer.active || stream.pending || !stream.editable,
      });
      const controls = node("div", { class: "pin-controls" }, weight);
      if (offer.active) {
        controls.append(
          button(
            offer.pin === null ? "Pin" : "Сохранить Pin",
            "",
            () =>
              runStream(
                stream,
                "edit",
                offer.offer_id,
                "pin",
                Number(weight.value),
              ),
            stream.pending || !stream.editable,
          ),
        );
        if (offer.pin !== null)
          controls.append(
            button(
              "Unpin",
              "",
              () => runStream(stream, "edit", offer.offer_id, "unpin"),
              stream.pending || !stream.editable,
            ),
          );
      } else
        controls.append(
          node("span", {
            class: "hint",
            text: offer.pin !== null ? `Pin ${offer.pin}%` : "—",
          }),
        );
      tr.append(node("td", {}, controls));
      tr.append(
        node(
          "td",
          { class: "offer-action" },
          button(
            offer.active ? "Remove" : "Bring back",
            "",
            () =>
              runStream(
                stream,
                "edit",
                offer.offer_id,
                offer.active ? "remove" : "restore",
              ),
            stream.pending || !stream.editable,
          ),
        ),
      );
      tbody.append(tr);
    }
    table.append(tbody);
    card.append(node("div", { class: "table-scroll" }, table));
  }
  if (stream.editable) {
    const searchID = `offer-search-${stream.id}`;
    const input = node("input", {
      id: searchID,
      type: "text",
      list: `offer-options-${stream.id}`,
      placeholder: "ID или название оффера",
      autocomplete: "off",
      disabled: stream.pending,
    });
    const list = node("datalist", { id: `offer-options-${stream.id}` });
    const hint = node("span", {
      class: "hint search-hint",
      "aria-live": "polite",
      text: "Поиск в Keitaro",
    });
    autocomplete(input, list, hint, "offers");
    const add = button(
      "Добавить",
      "secondary",
      () => {
        try {
          runStream(stream, "add", numericID(input));
        } catch (error) {
          message(error.message);
        }
      },
      stream.pending,
    );
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        add.click();
      }
    });
    const bottom = node(
      "div",
      { class: "stream-bottom" },
      node(
        "div",
        { class: "stream-add" },
        node(
          "div",
          { class: "search-field" },
          node("label", { htmlFor: searchID, text: "Добавить оффер" }),
          input,
          list,
        ),
        add,
      ),
      hint,
    );
    bottom.append(
      node(
        "div",
        { class: "stream-controls" },
        node(
          "div",
          { class: "stream-total" },
          `Активных: ${stream.active_count} · Сумма: `,
          node("strong", { text: `${stream.total}%` }),
        ),
        node(
          "div",
          { class: "buttons" },
          button(
            "Cancel",
            "secondary",
            () => runStream(stream, "cancel"),
            !stream.dirty || stream.pending,
          ),
          button(
            "Publish",
            "primary",
            () => runStream(stream, "publish"),
            (!stream.dirty && !stream.pending) ||
              stream.active_count === 0 ||
              stream.total !== 100,
          ),
        ),
      ),
    );
    card.append(bottom);
  }
  if (!stream.editable && stream.dirty && !stream.pending) {
    card.append(
      node(
        "div",
        { class: "stream-bottom" },
        button("Cancel", "secondary", () => runStream(stream, "cancel")),
      ),
    );
  }
  if (
    stream.notice ||
    stream.pending ||
    (stream.editable && stream.total !== 100)
  ) {
    card.append(
      node("p", {
        class: "notice",
        text: stream.pending
          ? "Результат публикации неизвестен. Publish сверит состояние без повторной записи. Если результат не подтверждён, требуется ручная сверка в Keitaro."
          : stream.notice ||
            "Для публикации сумма активных весов должна быть 100%.",
      }),
    );
  }
  return card;
}

async function selectCampaign(id, sync = true) {
  if (working) return;
  setWorking(true);
  $("#campaign-loader button").disabled = true;
  $("#sync").disabled = true;
  message("");
  try {
    current = await api(
      `/campaigns/${id}${sync ? "/sync" : ""}`,
      sync ? "POST" : "GET",
    );
    store("adrobot.campaign", id);
  } catch (error) {
    if (sync && error.code === "dirty_sync") {
      try {
        current = await api(`/campaigns/${id}`);
        store("adrobot.campaign", id);
        message(
          "Открыт сохранённый черновик. Перед синхронизацией выполните Publish или Cancel.",
        );
      } catch (localError) {
        message(localError.message);
      }
    } else message(error.message);
  } finally {
    setWorking(false);
    $("#campaign-loader button").disabled = false;
    render();
  }
}

async function runStream(stream, action, offerID, editAction, pin) {
  if (working) return;
  setWorking(true);
  const card = $(`#stream-${stream.id}`);
  card.setAttribute("aria-busy", "true");
  card
    .querySelectorAll("button,input")
    .forEach((element) => (element.disabled = true));
  $("#sync").disabled = true;
  message("");
  try {
    let path = `/streams/${stream.id}`;
    let method = "POST";
    const body = { revision: stream.revision };
    if (action === "add") {
      path += "/offers";
      body.offer_id = offerID;
    } else if (action === "edit") {
      path += `/offers/${offerID}`;
      method = "PATCH";
      body.action = editAction;
      if (editAction === "pin") body.pin = pin;
    } else path += `/${action}`;
    const updated = await api(path, method, body);
    current.streams = current.streams.map((item) =>
      item.id === stream.id ? updated : item,
    );
  } catch (error) {
    message(error.message);
    try {
      current = await api(`/campaigns/${current.id}`);
    } catch {
      /* Retain the last known draft. */
    }
  } finally {
    setWorking(false);
    render();
  }
}

$("#creator").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (working) return;
  let body;
  try {
    body = {
      name: $("#campaign-name").value.trim(),
      countries: $("#countries")
        .value.split(/[,;\s]+/)
        .filter(Boolean),
      offer_id: numericID($("#creator-offer")),
      domain_id: numericID($("#domain")),
      group_id: numericID($("#group")),
      traffic_source_id: numericID($("#source")),
    };
  } catch (error) {
    message(error.message);
    return;
  }
  let operation = readStored("adrobot.creation");
  if (
    operation &&
    comparableCreation(operation.body) !== comparableCreation(body)
  ) {
    message(
      "Параметры сохранённой операции отличаются. Для сверки верните исходные параметры или перезагрузите страницу. Для другой кампании нажмите «Начать новую операцию»; это не отменяет предыдущую запись в Keitaro.",
    );
    return;
  }
  if (!operation) {
    operation = { key: crypto.randomUUID(), body };
    store("adrobot.creation", operation);
  }
  body = operation.body;
  setWorking(true);
  $("#creator-fields").disabled = true;
  message("");
  $("#creation-result").textContent = "Создание кампании…";
  $("#new-operation").hidden = false;
  let result;
  try {
    result = await api("/campaigns", "POST", body, {
      "Idempotency-Key": operation.key,
    });
    $("#creation-result").textContent =
      `Кампания #${result.campaign_id} создана. Повторная отправка этой формы вернёт ту же кампанию.`;
  } catch (error) {
    $("#creation-result").textContent =
      "Операция сохранена. Повторная отправка с теми же параметрами выполнит сверку без создания дубликата.";
    message(error.message);
  } finally {
    setWorking(false);
    $("#creator-fields").disabled = false;
  }
  if (result) {
    await selectCampaign(result.campaign_id, true);
    if (current?.id === result.campaign_id)
      message(`Кампания #${result.campaign_id} создана и загружена.`, true);
  }
});

$("#campaign-loader").addEventListener("submit", (event) => {
  event.preventDefault();
  try {
    selectCampaign(numericID($("#campaign-search")));
  } catch (error) {
    message(error.message);
  }
});
$("#sync").addEventListener(
  "click",
  () => current && selectCampaign(current.id),
);
$("#local-refresh").addEventListener(
  "click",
  () => current && selectCampaign(current.id, false),
);
$("#retry-connection").addEventListener("click", () => {
  message("");
  connect();
});
$("#new-operation").addEventListener("click", () => {
  if (working) return;
  store("adrobot.creation", null);
  $("#creation-result").textContent = "";
  $("#campaign-name").value = "test_tsybizov_";
  $("#campaign-name").focus();
  $("#new-operation").hidden = true;
});
$("#copy-url").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(current.tracking_url);
    message("Ссылка скопирована.", true);
  } catch {
    message("Не удалось скопировать ссылку. Выделите её и скопируйте вручную.");
  }
});
autocomplete(
  $("#creator-offer"),
  $("#creator-offers"),
  $("#creator-offer-hint"),
  "offers",
);
autocomplete(
  $("#campaign-search"),
  $("#campaign-options"),
  $("#campaign-search-hint"),
  "campaigns",
);

async function start() {
  await connect();
  const operation = readStored("adrobot.creation");
  if (operation?.body) {
    $("#campaign-name").value = operation.body.name;
    $("#countries").value = operation.body.countries.join(", ");
    $("#creator-offer").value = operation.body.offer_id;
    for (const [field, key] of [
      ["domain", "domain_id"],
      ["group", "group_id"],
      ["source", "traffic_source_id"],
    ]) {
      if (
        [...$(`#${field}`).options].some(
          (option) => Number(option.value) === operation.body[key],
        )
      )
        $(`#${field}`).value = operation.body[key];
    }
    $("#new-operation").hidden = false;
  }
  const saved = readStored("adrobot.campaign");
  if (Number.isSafeInteger(saved) && saved > 0)
    await selectCampaign(saved, false);
}
start();
