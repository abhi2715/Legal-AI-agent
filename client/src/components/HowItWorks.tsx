import { useEffect, useRef } from 'react';
import { Upload, Search, CheckCircle } from 'lucide-react';
import './HowItWorks.css';

const steps = [
  {
    icon: Upload,
    step: '01',
    title: 'Upload Your Contract',
    description: 'Drop your PDF or text file. Your document is processed securely and never stored permanently.',
  },
  {
    icon: Search,
    step: '02',
    title: 'Ask Any Question',
    description: 'Type a question in plain English — or pick from our suggested queries for common clauses.',
  },
  {
    icon: CheckCircle,
    step: '03',
    title: 'Get Cited Answers',
    description: 'Receive precise answers with source citations, sentiment analysis, and paraphrased explanations.',
  },
];

export default function HowItWorks() {
  const sectionRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add('hiw--visible');
          }
        });
      },
      { threshold: 0.2 }
    );

    if (sectionRef.current) observer.observe(sectionRef.current);
    return () => observer.disconnect();
  }, []);

  return (
    <section className="hiw section" id="how-it-works" ref={sectionRef}>
      <div className="container">
        <div className="hiw__header">
          <span className="pill pill-accent">How It Works</span>
          <h2 className="hiw__title">
            Three steps to <span className="gradient-text">contract clarity</span>
          </h2>
        </div>

        <div className="hiw__steps">
          {steps.map((s, i) => {
            const Icon = s.icon;
            return (
              <div key={s.step} className="hiw__step" style={{ animationDelay: `${i * 200}ms` }}>
                <div className="hiw__step-number">{s.step}</div>
                <div className="hiw__step-icon">
                  <Icon size={28} />
                </div>
                <h3 className="hiw__step-title">{s.title}</h3>
                <p className="hiw__step-desc">{s.description}</p>
                {i < steps.length - 1 && <div className="hiw__connector" />}
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
