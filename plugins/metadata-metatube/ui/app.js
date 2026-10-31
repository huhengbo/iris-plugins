(function () {
  "use strict";

  // 分组和顺序与 Jellyfin/Emby 的 MetaTube 设置页一致
  var SECTIONS = [
    {
      title: "常规",
      fields: [
        "server",
        "token",
        "enable_directors",
        "enable_ratings",
        "enable_real_actor_names",
      ],
    },
    { title: "图片", fields: ["primary_image_ratio", "image_quality"] },
    { title: "来源", fields: ["enable_provider_filter", "provider_filter"] },
    { title: "模板", fields: ["enable_template", "name_template", "tagline_template"] },
    {
      title: "翻译",
      fields: [
        "translation_mode",
        "translation_engine",
        "translation_language",
        "baidu_app_id",
        "baidu_app_key",
        "google_api_key",
        "google_api_url",
        "deepl_api_key",
        "deepl_api_url",
        "openai_api_key",
        "openai_api_url",
        "openai_model",
      ],
    },
    {
      title: "替换",
      fields: [
        "enable_title_substitution",
        "title_substitution_table",
        "enable_actor_substitution",
        "actor_substitution_table",
        "enable_genre_substitution",
        "genre_substitution_table",
      ],
    },
  ];
  var OPTION_LABELS = {
    translation_mode: { disabled: "关闭", title: "标题", summary: "简介", both: "标题和简介" },
    translation_engine: {
      Baidu: "百度",
      Google: "Google",
      GoogleFree: "Google（免费）",
      DeepL: "DeepL",
      OpenAI: "OpenAI",
    },
  };
  var ENGINE_FIELDS = {
    Baidu: ["baidu_app_id", "baidu_app_key"],
    Google: ["google_api_key", "google_api_url"],
    GoogleFree: [],
    DeepL: ["deepl_api_key", "deepl_api_url"],
    OpenAI: ["openai_api_key", "openai_api_url", "openai_model"],
  };
  var TEXTAREAS = {
    title_substitution_table: 5,
    actor_substitution_table: 5,
    genre_substitution_table: 5,
  };

  var form = document.getElementById("settings");
  var statusLine = document.getElementById("status-line");
  var iris = null;
  var rows = {};
  var busy = false;
  var saveButton = null;
  var testButton = null;
  var formStatus = null;

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function setStatus(message, kind) {
    formStatus.textContent = message || "";
    formStatus.className = "iris-form-status" + (kind ? " iris-" + kind : "");
  }

  function setBusy(value) {
    busy = value;
    saveButton.disabled = value;
    if (testButton) testButton.disabled = value;
  }

  function showHeader(data) {
    var parts = [];
    parts.push(data && data.server ? "服务器 " + data.server : "尚未填写服务器地址");
    parts.push(data && data.token_set ? "已设置令牌" : "未设置令牌");
    statusLine.textContent = parts.join("；") + "。";
    statusLine.className = data && data.server ? "iris-success" : "iris-muted";
  }

  function loadHeader() {
    iris.json("status").then(showHeader, function (error) {
      statusLine.textContent = (error && error.message) || "读取状态失败";
      statusLine.className = "iris-error";
    });
  }

  function createRow(field, value) {
    var row = { field: field, box: el("div", "iris-field"), input: null, clear: false };
    var id = "mt-" + field.name;
    if (field.kind === "bool") {
      var label = el("label", "iris-checkbox");
      var check = el("input", "iris-checkbox-input");
      check.type = "checkbox";
      check.id = id;
      check.checked = value === true;
      label.appendChild(check);
      label.appendChild(el("span", "", field.label));
      row.box.appendChild(label);
      row.input = check;
    } else {
      var title = el("label", "", field.label);
      title.setAttribute("for", id);
      if (field.required) title.appendChild(el("span", "iris-required", " *"));
      row.box.appendChild(title);
      if (field.kind === "select") {
        var select = el("select", "iris-select");
        select.id = id;
        (field.options || []).forEach(function (option) {
          var node = el("option", "", (OPTION_LABELS[field.name] || {})[option] || option);
          node.value = option;
          select.appendChild(node);
        });
        select.value = value;
        row.input = select;
        row.box.appendChild(select);
      } else if (field.kind === "secret") {
        var wrap = el("div", "mt-secret");
        var secret = el("input", "iris-secret-input");
        secret.type = "password";
        secret.id = id;
        secret.autocomplete = "new-password";
        var clear = el("button", "iris-secondary iris-small", "清除");
        clear.type = "button";
        row.input = secret;
        row.isSet = !!(value && value.set);
        function refresh() {
          secret.placeholder = row.clear ? "保存后清除" : row.isSet ? "已设置，留空保持不变" : "";
          clear.hidden = !row.isSet || row.clear;
        }
        clear.addEventListener("click", function () {
          row.clear = true;
          secret.value = "";
          refresh();
        });
        secret.addEventListener("input", function () {
          row.clear = false;
          refresh();
        });
        refresh();
        wrap.appendChild(secret);
        wrap.appendChild(clear);
        row.box.appendChild(wrap);
      } else if (TEXTAREAS[field.name]) {
        var area = el("textarea");
        area.id = id;
        area.rows = TEXTAREAS[field.name];
        area.maxLength = field.max_length || 20000;
        area.value = value || "";
        row.input = area;
        row.box.appendChild(area);
      } else {
        var input = el("input");
        input.id = id;
        input.type = field.kind === "number" ? "number" : field.kind === "url" ? "url" : "text";
        input.autocomplete = "off";
        if (field.kind === "number") {
          input.step = "any";
          if (field.min !== null && field.min !== undefined) input.min = String(field.min);
          if (field.max !== null && field.max !== undefined) input.max = String(field.max);
        } else if (field.max_length) {
          input.maxLength = field.max_length;
        }
        input.value = value === null || value === undefined ? "" : String(value);
        row.input = input;
        row.box.appendChild(input);
      }
    }
    if (field.help) row.box.appendChild(el("p", "iris-field-help", field.help));
    return row;
  }

  function readRow(row) {
    var field = row.field;
    if (field.kind === "bool") return row.input.checked;
    if (field.kind === "number") {
      return row.input.value.trim() === "" ? null : Number(row.input.value);
    }
    if (field.kind === "secret") {
      if (row.clear) return null;
      return row.input.value === "" ? undefined : row.input.value;
    }
    return row.input.value;
  }

  function collect() {
    var body = {};
    Object.keys(rows).forEach(function (name) {
      var value = readRow(rows[name]);
      if (value !== undefined) body[name] = value;
    });
    return body;
  }

  // 翻译关闭时隐藏引擎相关项；引擎相关项按所选引擎显示（与 Jellyfin 页面一致）
  function applyVisibility() {
    var enabled = rows.translation_mode.input.value !== "disabled";
    var engine = rows.translation_engine.input.value;
    var engineFields = [];
    Object.keys(ENGINE_FIELDS).forEach(function (key) {
      engineFields = engineFields.concat(ENGINE_FIELDS[key]);
    });
    rows.translation_engine.box.classList.toggle("mt-hidden", !enabled);
    rows.translation_language.box.classList.toggle("mt-hidden", !enabled);
    engineFields.forEach(function (name) {
      var shown = enabled && (ENGINE_FIELDS[engine] || []).indexOf(name) >= 0;
      if (rows[name]) rows[name].box.classList.toggle("mt-hidden", !shown);
    });
  }

  function render(data) {
    rows = {};
    busy = false;
    form.textContent = "";
    var byName = {};
    (data.fields || []).forEach(function (field) {
      byName[field.name] = field;
    });
    var placed = {};
    var sections = SECTIONS.slice();
    sections.forEach(function (section) {
      section.fields.forEach(function (name) {
        placed[name] = true;
      });
    });
    // 以后新增的字段不会因为没写进分组而丢失
    var extra = Object.keys(byName).filter(function (name) {
      return !placed[name];
    });
    if (extra.length) sections.push({ title: "其他", fields: extra });

    sections.forEach(function (section) {
      form.appendChild(el("h3", "mt-section", section.title));
      section.fields.forEach(function (name) {
        var field = byName[name];
        if (!field) return;
        var row = createRow(field, (data.values || {})[name]);
        rows[name] = row;
        form.appendChild(row.box);
      });
    });

    var actions = el("div", "iris-actions");
    saveButton = el("button", "", "保存");
    saveButton.type = "submit";
    actions.appendChild(saveButton);
    if (data.testable) {
      testButton = el("button", "iris-secondary", "测试连接");
      testButton.type = "button";
      testButton.addEventListener("click", testConnection);
      actions.appendChild(testButton);
    }
    form.appendChild(actions);
    formStatus = el("p", "iris-form-status");
    formStatus.setAttribute("role", "status");
    formStatus.setAttribute("aria-live", "polite");
    form.appendChild(formStatus);

    rows.translation_mode.input.addEventListener("change", applyVisibility);
    rows.translation_engine.input.addEventListener("change", applyVisibility);
    applyVisibility();
  }

  function fail(error, fallback) {
    var message = (error && error.message) || fallback;
    setStatus(message, "error");
    IrisPlugin.toast(message);
  }

  function save() {
    if (busy) return;
    setBusy(true);
    setStatus("保存中…");
    iris.json("settings", { method: "PUT", json: collect() }).then(
      function (data) {
        render(data);
        setStatus("已保存", "success");
        IrisPlugin.toast("已保存");
        loadHeader();
      },
      function (error) {
        setBusy(false);
        fail(error, "保存失败");
      }
    );
  }

  function testConnection() {
    if (busy) return;
    setBusy(true);
    setStatus("测试中…");
    iris.json("settings/test", { method: "POST", json: collect() }).then(
      function (result) {
        setBusy(false);
        if (result && result.ok) {
          setStatus("连接成功", "success");
          IrisPlugin.toast("连接成功");
        } else {
          fail({ message: (result && result.message) || "测试失败" }, "测试失败");
        }
      },
      function (error) {
        setBusy(false);
        fail(error, "测试失败");
      }
    );
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    save();
  });

  IrisPlugin.ready()
    .then(function (plugin) {
      iris = plugin;
      loadHeader();
      return iris.json("settings");
    })
    .then(function (data) {
      render(data);
    })
    .catch(function (error) {
      statusLine.textContent = (error && error.message) || "加载设置失败";
      statusLine.className = "iris-error";
      IrisPlugin.toast(statusLine.textContent);
    });
})();
