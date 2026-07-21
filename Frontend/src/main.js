const benefits = [
  {
    icon: "clock",
    title: "Save Hours",
    detail: "Every Week",
  },
  {
    icon: "target",
    title: "Reduce Waste",
    detail: "and Shrink",
  },
  {
    icon: "chart",
    title: "Make Smarter",
    detail: "Purchasing Decisions",
  },
];

function iconMarkup(name) {
  const icons = {
    clock: `
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="12" cy="12" r="9"></circle>
        <path d="M12 7v5l3 2"></path>
      </svg>
    `,
    target: `
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="12" cy="12" r="9"></circle>
        <circle cx="12" cy="12" r="4"></circle>
        <path d="M19 5l-4 4"></path>
        <path d="M20 2v4h-4"></path>
      </svg>
    `,
    chart: `
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 19h16"></path>
        <path d="M7 16v-4"></path>
        <path d="M12 16V8"></path>
        <path d="M17 16V5"></path>
        <path d="M5 11l4-3 4 2 5-6"></path>
      </svg>
    `,
    spark: `
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 3l1.6 5.4L19 10l-5.4 1.6L12 17l-1.6-5.4L5 10l5.4-1.6L12 3z"></path>
        <path d="M18 15l.8 2.2L21 18l-2.2.8L18 21l-.8-2.2L15 18l2.2-.8L18 15z"></path>
      </svg>
    `,
  };

  return icons[name] || "";
}

function CTAButton({ label, href, variant = "primary", extraClass = "" }) {
  return `
    <a class="cta-button cta-button--${variant} ${extraClass}" href="${href}">
      <span>${label}</span>
      <span class="cta-arrow" aria-hidden="true">→</span>
    </a>
  `;
}

function BenefitItem({ icon, title, detail }) {
  return `
    <li class="benefit-item">
      <span class="benefit-icon">${iconMarkup(icon)}</span>
      <span class="benefit-copy">
        <strong>${title}</strong>
        <span>${detail}</span>
      </span>
    </li>
  `;
}

function Navbar() {
  return `
    <header class="navbar" aria-label="Main navigation">
      <a class="brand" href="#" aria-label="Koe home">Koe</a>
      <div class="nav-actions">
        ${CTAButton({ label: "Sign In", href: "/product.html", variant: "nav" })}
      </div>
    </header>
  `;
}

function HeroSection() {
  const benefitMarkup = benefits.map(BenefitItem).join("");

  return `
    <main class="hero">
      <div class="hero-panel" aria-hidden="true"></div>
      ${Navbar()}
      <section class="hero-content" aria-labelledby="hero-title">
        <div class="badge">
          <span class="badge-icon">${iconMarkup("spark")}</span>
          <span>AI FOR RESTAURANT OPERATIONS</span>
        </div>

        <h1 id="hero-title">
          <span>Inventory</span>
          <span>Management</span>
          <em>Made Easy</em>
        </h1>

        <div class="hairline" aria-hidden="true"></div>

        <p>
          AI-powered inventory counting with voice input, photo verification,
          and smart insights. Get accurate, real-time data so you can cut waste,
          control costs, and run a more profitable kitchen.
        </p>

        <div class="hero-actions">
          ${CTAButton({ label: "Use Koe", href: "/dashboard.html" })}
          ${CTAButton({ label: "Sign In/Up", href: "/product.html", variant: "secondary" })}
        </div>

        <ul class="benefit-row" aria-label="Koe benefits">${benefitMarkup}</ul>
      </section>
    </main>
  `;
}

function TransitionStrip() {
  return `
    <section class="koe-transition-section" aria-labelledby="inventory-night-title">
      <div class="koe-section-inner koe-transition-copy">
        <p class="koe-eyebrow koe-reveal">Built for inventory night.</p>
        <h2 class="koe-serif-heading koe-reveal koe-stagger-1" id="inventory-night-title">Count faster. Review cleaner. Buy smarter.</h2>
        <p class="koe-short-line koe-reveal koe-stagger-2">Voice, photo review, purchase planning, and CSV export in one clean flow.</p>
        <div class="koe-pill-row koe-reveal koe-stagger-3" aria-label="Koe workflow strengths">
          <span>Voice count</span>
          <span>Photo review</span>
          <span>Purchase plan</span>
          <span>CSV export</span>
        </div>
      </div>
    </section>
  `;
}

function ProductFlowSection() {
  return `
    <section class="koe-flow-section" aria-labelledby="product-flow-title">
      <div class="koe-section-inner">
        <div class="koe-section-heading koe-reveal">
          <p class="koe-eyebrow">Voice Count to Purchase List</p>
          <h2 class="koe-serif-heading" id="product-flow-title">Count it once. Leave with what to buy.</h2>
        </div>
        <div class="koe-flow-track">
          <article class="koe-flow-card koe-reveal koe-stagger-1">
            <div class="koe-flow-visual koe-flow-visual--dark" aria-hidden="true">
              <p>We have 2 boxes of tomatoes and need 6 more.</p>
            </div>
            <span>Speak naturally</span>
            <h3>Voice Count</h3>
          </article>
          <div class="koe-flow-connector koe-reveal koe-stagger-2" aria-hidden="true"></div>
          <article class="koe-flow-card koe-reveal koe-stagger-3">
            <div class="koe-flow-visual koe-flow-table" aria-hidden="true">
              <div class="koe-flow-row koe-row-delay-1"><span>Tomatoes</span><b>2 boxes</b><em>Buy 6 boxes</em><i>Clean</i></div>
              <div class="koe-flow-row koe-row-delay-2"><span>Olive Oil</span><b>3 bottles</b><em>Buy 2 bottles</em><i>Clean</i></div>
              <div class="koe-flow-row koe-row-delay-3"><span>Limes</span><b>18 count</b><em>Buy 24 count</em><i>Clean</i></div>
            </div>
            <span>Koe structures it</span>
            <h3>Clean Report</h3>
          </article>
          <div class="koe-flow-connector koe-reveal koe-stagger-4" aria-hidden="true"></div>
          <article class="koe-flow-card koe-reveal koe-stagger-5">
            <div class="koe-flow-visual koe-flow-report" aria-hidden="true">
              <strong>Purchase List</strong>
              <small>Next order draft</small>
              <div class="koe-flow-report-list">
                <span>Tomatoes <b>6 boxes</b></span>
                <span>Olive Oil <b>2 bottles</b></span>
                <span>Limes <b>24 count</b></span>
              </div>
              <button type="button" tabindex="-1">Export CSV</button>
            </div>
            <span>Review anytime</span>
            <h3>Purchase List</h3>
          </article>
        </div>
      </div>
    </section>
  `;
}

function DarkProductPanel() {
  const rows = [
    ["Tomatoes", "2 boxes", "6 boxes", "Clean", "clean"],
    ["Olive Oil", "3 bottles", "2 bottles", "Clean", "clean"],
    ["Limes", "18 count", "24 count", "Clean", "clean"],
    ["Napkins", "1 case", "2 cases", "Clean", "clean"],
  ];
  return `
    <section class="koe-dark-section" aria-labelledby="clean-count-title">
      <div class="koe-section-inner koe-dark-grid">
        <div class="koe-dark-copy">
          <p class="koe-eyebrow koe-reveal">THE CLEAN COUNT</p>
          <h2 class="koe-serif-heading koe-reveal koe-stagger-1" id="clean-count-title">Everything lands where it should.</h2>
          <p class="koe-reveal koe-stagger-2">Current quantity, quantity to purchase, review flags, and saved history - all organized before the shift ends.</p>
        </div>
        <article class="koe-report-mockup koe-reveal koe-stagger-2">
          <div class="koe-report-topline">
            <div>
              <span>Closing Count Report</span>
              <strong>Walk-in inventory</strong>
            </div>
          </div>
          <div class="koe-report-table" aria-hidden="true">
            <div class="koe-report-row koe-report-row--head">
              <span>Item</span>
              <span>Current</span>
              <span>To Purchase</span>
              <span>Status</span>
            </div>
            ${rows
              .map(
                ([item, current, purchase, status, tone], index) => `
                  <div class="koe-report-row koe-reveal koe-stagger-${index + 1}">
                    <span>${item}</span>
                    <span>${current}</span>
                    <span>${purchase}</span>
                    <span><i class="koe-status koe-status--${tone}">${status}</i></span>
                  </div>
                `,
              )
              .join("")}
          </div>
        </article>
      </div>
    </section>
  `;
}

function FeatureGridSection() {
  const cards = [
    {
      title: "Voice to spreadsheet.",
      text: "Count out loud. Koe builds the rows.",
      visual: `
        <div class="koe-mini-wave"><i></i><i></i><i></i><i></i><i></i></div>
        <p>tomatoes, olive oil, limes</p>
      `,
    },
    {
      title: '<span class="koe-accent-title">Photo counts.</span>',
      text: "Snap inventory areas and review detected items.",
      visual: `
        <div class="koe-mini-photo-frame">
          <span class="koe-photo-badge">Clean row preview</span>
          <div class="koe-photo-tags">
            <b>Olive Oil - 3 bottles</b>
            <b>Lettuce - 5 heads</b>
            <b>Tomato Boxes - 4 boxes</b>
          </div>
        </div>
      `,
    },
    {
      title: '<span class="koe-accent-title">Quantity to Purchase.</span>',
      text: "Separate what you have from what you need to buy.",
      visual: `
        <div class="koe-mini-purchase-row"><span>Tomatoes</span><b>Buy 6 boxes</b></div>
      `,
    },
    {
      title: '<span class="koe-accent-title">Forecast restocks.</span>',
      text: "Use sales, recipes, and stock to plan next week.",
      visual: `
        <div class="koe-mini-forecast-flow">
          <div class="koe-mini-forecast-node">Sales</div>
          <div class="koe-mini-forecast-node">Recipes</div>
          <div class="koe-mini-forecast-node">Stock</div>
          <div class="koe-mini-forecast-arrow">→</div>
          <div class="koe-mini-forecast-list">
            <span><em>Tomatoes</em><b>6 boxes</b></span>
            <span><em>Milk</em><b>4 gallons</b></span>
          </div>
        </div>
      `,
    },
    {
      title: "Past Count History.",
      text: "Saved counts stay organized by year and month.",
      visual: `
        <div class="koe-mini-history"><strong>2026</strong><span>July</span><span>Walk-in count</span></div>
      `,
    },
    {
      title: '<span class="koe-accent-title">CSV export.</span>',
      text: "Send clean reports wherever the restaurant already works.",
      visual: `
        <div class="koe-mini-csv"><strong>CSV</strong><span>Export ready</span></div>
      `,
    },
  ];

  return `
    <section class="koe-feature-section" aria-labelledby="feature-grid-title">
      <div class="koe-section-inner">
        <div class="koe-section-heading koe-reveal">
          <p class="koe-eyebrow">WHAT KOE KEEPS CLEAN</p>
          <h2 class="koe-serif-heading" id="feature-grid-title">Efficient workflow.</h2>
        </div>
        <div class="koe-feature-grid">
          ${cards
            .map(
              (card, index) => `
                <article class="koe-feature-card koe-reveal koe-stagger-${index + 1}">
                  <div class="koe-feature-visual" aria-hidden="true">${card.visual}</div>
                  <h3>${card.title}</h3>
                  <p>${card.text}</p>
                </article>
              `,
            )
            .join("")}
        </div>
      </div>
    </section>
  `;
}

function ForecastSection() {
  const inputs = [
    ["Last month sales", "Menu item volume"],
    ["Recipe ingredients", "What each plate uses"],
    ["Current inventory", "What is on hand now"],
  ];
  const purchaseRows = [
    ["Tomatoes", "6 boxes"],
    ["Chicken Breast", "20 lb"],
    ["Whole Milk", "4 gallons"],
    ["Paper Cups", "500 cups"],
  ];

  return `
    <section class="koe-forecast-section" aria-labelledby="forecast-title">
      <div class="koe-section-inner koe-forecast-grid">
        <div class="koe-forecast-copy koe-reveal">
          <p class="koe-eyebrow">Next Week Restock Planning</p>
          <h2 class="koe-serif-heading" id="forecast-title">Plan next week before you run out.</h2>
          <p>Sales data, recipes, and current stock become a suggested purchase list.</p>
        </div>
        <div class="koe-forecast-visual" aria-label="Forecast restock planning visual">
          <div class="koe-forecast-inputs">
            ${inputs
              .map(
                ([title, detail], index) => `
                  <div class="koe-forecast-input-card koe-reveal koe-stagger-${index + 1}">
                    <span>${title}</span>
                    <b>${detail}</b>
                  </div>
                `,
              )
              .join("")}
          </div>
          <div class="koe-forecast-connector koe-reveal koe-stagger-3" aria-hidden="true"></div>
          <article class="koe-forecast-plan koe-reveal koe-stagger-4">
            <span>Suggested Purchase List</span>
            <strong>Next week purchase plan</strong>
            <div>
              ${purchaseRows
                .map(
                  ([item, quantity]) => `
                    <p><span>${item}</span><b>${quantity}</b><i>Clean</i></p>
                  `,
                )
                .join("")}
            </div>
          </article>
        </div>
      </div>
    </section>
  `;
}

function HowItWorksSection() {
  const steps = [
    ["01", "Speak", "Say the inventory count naturally."],
    ["02", "Structure", "Koe cleans items, units, quantities, and purchase needs."],
    ["03", "Export", "Review, save, or download the CSV."],
  ];
  return `
    <section class="koe-steps-section" aria-labelledby="steps-title">
      <div class="koe-section-inner">
        <div class="koe-section-heading koe-section-heading--center koe-reveal">
          <h2 class="koe-serif-heading" id="steps-title">From count to report in minutes.</h2>
        </div>
        <div class="koe-steps-grid">
          ${steps
            .map(
              ([number, title, text], index) => `
                <article class="koe-step-card koe-reveal koe-stagger-${index + 1}">
                  <b aria-hidden="true">${number}</b>
                  <span>${number}</span>
                  <h3>${title}</h3>
                  <p>${text}</p>
                </article>
              `,
            )
            .join("")}
        </div>
      </div>
    </section>
  `;
}

function FinalCtaSection() {
  return `
    <section class="koe-final-section" aria-labelledby="final-cta-title">
      <div class="koe-section-inner">
        <article class="koe-final-card koe-reveal">
          <p class="koe-eyebrow">READY WHEN THE COUNT STARTS</p>
          <h2 class="koe-serif-heading" id="final-cta-title">Ready to clean up inventory night?</h2>
          <p>Count by voice, review by photo, and plan what to buy next.</p>
          <div class="koe-final-actions">
            ${CTAButton({ label: "Start Counting", href: "/dashboard.html" })}
            ${CTAButton({ label: "Sign In", href: "/product.html", variant: "secondary" })}
          </div>
        </article>
      </div>
    </section>
  `;
}

function LandingStory() {
  return `
    <div class="koe-landing-story">
      ${TransitionStrip()}
      ${ProductFlowSection()}
      ${DarkProductPanel()}
      ${FeatureGridSection()}
      ${ForecastSection()}
      ${HowItWorksSection()}
      ${FinalCtaSection()}
    </div>
  `;
}

function LandingPage() {
  return `${HeroSection()}${LandingStory()}`;
}

function initKoeRevealAnimations() {
  const revealItems = Array.from(document.querySelectorAll(".koe-reveal"));
  if (!revealItems.length) return;

  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (prefersReducedMotion || !("IntersectionObserver" in window)) {
    revealItems.forEach((item) => item.classList.add("is-visible"));
    return;
  }

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    },
    {
      rootMargin: "0px 0px -12% 0px",
      threshold: 0.16,
    },
  );

  revealItems.forEach((item) => observer.observe(item));
}

document.querySelector("#app").innerHTML = LandingPage();
initKoeRevealAnimations();
