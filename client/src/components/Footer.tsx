import { Scale } from 'lucide-react';
import './Footer.css';

export default function Footer() {
  return (
    <footer className="footer">
      <div className="container">
        <div className="footer__inner">
          <div className="footer__brand">
            <div className="footer__logo">
              <Scale size={18} />
              <span>
                Lexi<span className="gradient-text">Scan</span>
              </span>
            </div>
            <p className="footer__tagline">
              AI-powered contract analysis for modern teams.
            </p>
          </div>

          <div className="footer__bottom">
            <p className="footer__copy">
              © {new Date().getFullYear()} Abhishek KS | LexiScan AI. For research & educational purposes only.
            </p>
            <p className="footer__disclaimer">
              Not a substitute for professional legal advice.
            </p>
          </div>
        </div>
      </div>
    </footer>
  );
}
