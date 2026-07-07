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
          ${CTAButton({ label: "Open Koe", href: "/product.html" })}
          ${CTAButton({ label: "Sign In", href: "/product.html", variant: "secondary" })}
        </div>

        <ul class="benefit-row" aria-label="Koe benefits">${benefitMarkup}</ul>
      </section>
    </main>
  `;
}

document.querySelector("#app").innerHTML = HeroSection();
