const inventoryRows = [
  { icon: "🫒", name: "Olive oil", quantity: "2.5", unit: "bottles", source: "Voice" },
  { icon: "🥬", name: "Lettuce", quantity: "3", unit: "heads", source: "Voice" },
  { icon: "🍅", name: "Tomatoes", quantity: "5", unit: "boxes", source: "Voice" },
  { icon: "🧀", name: "Cheese", quantity: "2", unit: "boxes", source: "Voice" },
];

function ProductIcon(name) {
  const icons = {
    plus: `<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"></path></svg>`,
    pin: `<svg viewBox="0 0 24 24"><path d="M12 21s7-6.1 7-12a7 7 0 0 0-14 0c0 5.9 7 12 7 12z"></path><circle cx="12" cy="9" r="2.2"></circle></svg>`,
    edit: `<svg viewBox="0 0 24 24"><path d="M4 20h4l11-11-4-4L4 16v4z"></path><path d="M13.5 6.5l4 4"></path></svg>`,
    file: `<svg viewBox="0 0 24 24"><path d="M7 3h7l5 5v13H7z"></path><path d="M14 3v6h5"></path><path d="M9 14h6M9 17h6"></path></svg>`,
    export: `<svg viewBox="0 0 24 24"><path d="M12 3v12"></path><path d="M7 10l5 5 5-5"></path><path d="M5 21h14"></path></svg>`,
    sheet: `<svg viewBox="0 0 24 24"><path d="M7 3h10v18H7z"></path><path d="M7 8h10M7 13h10M12 8v13"></path></svg>`,
    shield: `<svg viewBox="0 0 24 24"><path d="M12 3l8 3v6c0 5-3.4 8.2-8 9-4.6-.8-8-4-8-9V6z"></path><path d="M8.5 12l2.2 2.2 4.8-5"></path></svg>`,
    heart: `<svg viewBox="0 0 24 24"><path d="M20.5 8.5c0 5-8.5 10.5-8.5 10.5S3.5 13.5 3.5 8.5A4.5 4.5 0 0 1 12 6a4.5 4.5 0 0 1 8.5 2.5z"></path><path d="M7 12h3l1.4-3 2.2 6 1.4-3h2"></path></svg>`,
    mic: `<svg viewBox="0 0 24 24"><path d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3z"></path><path d="M5 11a7 7 0 0 0 14 0"></path><path d="M12 18v3"></path></svg>`,
  };
  return icons[name] || "";
}

function InventoryTable() {
  const rows = inventoryRows
    .map(
      (row) => `
        <tr>
          <td class="drag-cell">⋮</td>
          <td><span class="food-icon">${row.icon}</span>${row.name}</td>
          <td>${row.quantity}</td>
          <td>${row.unit}</td>
          <td>${row.source}</td>
          <td><span class="status-pill">✓ Confirmed</span></td>
        </tr>
      `,
    )
    .join("");

  return `
    <table class="product-table">
      <thead>
        <tr>
          <th></th>
          <th>Name</th>
          <th>Quantity</th>
          <th>Unit</th>
          <th>Source</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function ProductWorkspace() {
  return `
    <main class="product-shell">
      <header class="product-topbar">
        <a href="./index.html" class="product-logo">Koe</a>
        <div class="product-title-block">
          <h1>Inventory Count Workspace</h1>
          <p>Dry Storage <span>•</span> May 14, 2025 9:15 AM <strong>In Progress</strong></p>
        </div>
        <button class="location-picker" type="button">
          <span>${ProductIcon("pin")}</span>
          <span><strong>The Garden Bistro</strong><small>Downtown Location</small></span>
          <span class="picker-chevron">⌄</span>
        </button>
        <button class="new-count-button" type="button">${ProductIcon("plus")} Start New Count</button>
      </header>

      <section class="product-grid" aria-label="Inventory count workspace">
        <div class="workspace-column">
          <section class="workspace-card voice-card">
            <div class="section-heading">
              <div>
                <span class="step-number">01</span>
                <h2>Count by Voice</h2>
                <p>Speak naturally. Koe will capture, transcribe, and structure your count.</p>
              </div>
              <div class="listening-pill"><span></span> Listening... <i></i></div>
            </div>
            <div class="voice-capture">
              <div class="mic-panel">
                <div class="mic-ring"><div class="mic-core">${ProductIcon("mic")}</div></div>
                <strong>00:18</strong>
                <button type="button">Stop Recording</button>
              </div>
              <div class="transcript-panel">
                <p>We have 3 bottles of olive oil, one of which is half empty, 3 heads of lettuce, 5 boxes of tomatoes, and 2 boxes of cheese.</p>
                <div class="waveform" aria-hidden="true"></div>
              </div>
            </div>
          </section>

          <section class="workspace-card parsed-card">
            <div class="section-heading section-heading--row">
              <div>
                <span class="step-number">02</span>
                <h2>Parsed Inventory</h2>
                <p>Koe has turned your voice input into structured, clean data.</p>
              </div>
              <button class="ghost-button" type="button">${ProductIcon("edit")} Edit Items</button>
            </div>
            ${InventoryTable()}
            <div class="table-footer">
              <button class="add-item-button" type="button">${ProductIcon("plus")} Add Item</button>
              <span>4 items total</span>
            </div>
          </section>

          <section class="workspace-card review-card">
            <div class="review-icon">${ProductIcon("shield")}</div>
            <div>
              <h2>Review Issues</h2>
              <p>Great news! No critical issues found.</p>
              <small>You can still review your items or continue to generate your report.</small>
            </div>
            <button class="ghost-button" type="button">Review All Items</button>
          </section>
        </div>

        <aside class="insight-column" aria-label="Count tools">
          <section class="workspace-card summary-card">
            <h2>${ProductIcon("file")} Count Summary</h2>
            <dl>
              <div><dt>Total Items</dt><dd>4</dd></div>
              <div><dt>Needs Review</dt><dd>0</dd></div>
              <div><dt>Source</dt><dd>Voice Count</dd></div>
              <div><dt>Area</dt><dd>Dry Storage</dd></div>
              <div><dt>Started</dt><dd>May 14, 2025 9:15 AM</dd></div>
              <div><dt>Count ID</dt><dd>CNT-051425-01</dd></div>
            </dl>
          </section>

          <section class="workspace-card data-card">
            <h2>${ProductIcon("heart")} Data Health</h2>
            <p>We clean and normalize your data.</p>
            <div class="normalization-list">
              <div><span>EVOO</span><b>→</b><strong>Olive oil</strong><i>✓</i></div>
              <div><span>Roma tomatoes</span><b>→</b><strong>Tomatoes</strong><i>✓</i></div>
            </div>
            <small>✓ All items normalized</small>
          </section>

          <div class="report-actions">
            <button class="report-button report-button--primary" type="button">${ProductIcon("file")} Generate Report <span>→</span></button>
            <button class="report-button" type="button">${ProductIcon("export")} Export CSV</button>
            <button class="report-button" type="button">${ProductIcon("sheet")} Send to Sheets</button>
          </div>
        </aside>
      </section>
    </main>
  `;
}

document.querySelector("#product-app").innerHTML = ProductWorkspace();
