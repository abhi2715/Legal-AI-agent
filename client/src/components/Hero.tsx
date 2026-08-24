import { useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Sparkles } from 'lucide-react';
import './Hero.css';

export default function Hero() {
  const heroRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const hero = heroRef.current;
    if (!hero) return;

    const handleMouseMove = (e: MouseEvent) => {
      const rect = hero.getBoundingClientRect();
      const x = ((e.clientX - rect.left) / rect.width) * 100;
      const y = ((e.clientY - rect.top) / rect.height) * 100;
      hero.style.setProperty('--mouse-x', `${x}%`);
      hero.style.setProperty('--mouse-y', `${y}%`);
    };

    hero.addEventListener('mousemove', handleMouseMove);
    return () => hero.removeEventListener('mousemove', handleMouseMove);
  }, []);

  return (
    <section className="hero" ref={heroRef}>
      <div className="hero__glow" />
      <div className="hero__grid-bg" />

      <div className="container hero__content">
        <div className="hero__badge pill pill-accent animate-fade-in-up">
          <Sparkles size={14} />
          AI-Powered Contract Intelligence
        </div>

        <h1 className="hero__title animate-fade-in-up delay-1">
          Understand Any Contract
          <br />
          <span className="gradient-text">In Seconds.</span>
        </h1>

        <p className="hero__subtitle animate-fade-in-up delay-2">
          Upload your legal document and get instant, AI-powered answers to any question.
          Identify clauses, risks, and obligations — no lawyer required.
        </p>

        <div className="hero__actions animate-fade-in-up delay-3">
          <Link to="/analyze" className="btn btn-primary btn-lg">
            Start Analyzing
            <ArrowRight size={18} />
          </Link>
          <a href="#features" className="btn btn-secondary btn-lg">
            Explore Features
          </a>
        </div>

        <div className="hero__stats animate-fade-in-up delay-4">
          <div className="hero__stat">
            <span className="hero__stat-number">500+</span>
            <span className="hero__stat-label">Contracts Analyzed</span>
          </div>
          <div className="hero__stat-divider" />
          <div className="hero__stat">
            <span className="hero__stat-number">98%</span>
            <span className="hero__stat-label">Accuracy Rate</span>
          </div>
          <div className="hero__stat-divider" />
          <div className="hero__stat">
            <span className="hero__stat-number">&lt;5s</span>
            <span className="hero__stat-label">Average Response</span>
          </div>
        </div>
      </div>
    </section>
  );
}
