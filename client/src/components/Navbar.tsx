import { useState, useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Scale, Menu, X } from 'lucide-react';
import './Navbar.css';

export default function Navbar() {
  const [scrolled, setScrolled] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 20);
    window.addEventListener('scroll', onScroll);
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  useEffect(() => {
    setMobileOpen(false);
  }, [location]);

  return (
    <nav className={`navbar ${scrolled ? 'navbar--scrolled' : ''}`}>
      <div className="navbar__inner container-wide">
        <Link to="/" className="navbar__brand">
          <div className="navbar__logo-icon">
            <Scale size={22} />
          </div>
          <span className="navbar__logo-text">
            Lexi<span className="gradient-text">Scan</span>
          </span>
        </Link>

        <div className={`navbar__links ${mobileOpen ? 'navbar__links--open' : ''}`}>
          <Link to="/" className="navbar__link">Home</Link>
          <a href="/#features" className="navbar__link">Features</a>
          <a href="/#how-it-works" className="navbar__link">How It Works</a>
          <Link to="/analyze" className="navbar__cta btn btn-primary btn-sm">
            Launch App
          </Link>
        </div>

        <button
          className="navbar__toggle"
          onClick={() => setMobileOpen(!mobileOpen)}
          aria-label="Toggle menu"
        >
          {mobileOpen ? <X size={24} /> : <Menu size={24} />}
        </button>
      </div>
    </nav>
  );
}
