import { useEffect, useRef } from 'react';
import {
  FileSearch,
  MessageSquare,
  Shield,
  Zap,
  Brain,
  BarChart3,
} from 'lucide-react';
import './Features.css';

const features = [
  {
    icon: FileSearch,
    title: 'Smart Document Parsing',
    description: 'Upload any contract in PDF or TXT format. Our AI extracts and indexes every clause automatically.',
    color: 'violet',
  },
  {
    icon: MessageSquare,
    title: 'Conversational Q&A',
    description: 'Ask plain-English questions about your contract and receive precise, cited answers in seconds.',
    color: 'cyan',
  },
  {
    icon: Shield,
    title: 'Risk Identification',
    description: 'Detect potential risks, liabilities, and unfavorable terms before signing.',
    color: 'emerald',
  },
  {
    icon: Zap,
    title: 'Instant Analysis',
    description: 'Get results in under 5 seconds powered by fine-tuned transformer models.',
    color: 'amber',
  },
  {
    icon: Brain,
    title: 'Clause Paraphrasing',
    description: 'Complex legal jargon simplified into plain, easy-to-understand language using T5.',
    color: 'rose',
  },
  {
    icon: BarChart3,
    title: 'Sentiment Analysis',
    description: 'Understand the tone and implications of each clause — positive, negative, or neutral.',
    color: 'cyan',
  },
];

export default function Features() {
  const cardsRef = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add('features__card--visible');
          }
        });
      },
      { threshold: 0.15 }
    );

    cardsRef.current.forEach((card) => {
      if (card) observer.observe(card);
    });

    return () => observer.disconnect();
  }, []);

  return (
    <section className="features section" id="features">
      <div className="container">
        <div className="features__header">
          <span className="pill pill-accent">Features</span>
          <h2 className="features__title">
            Everything you need to <span className="gradient-text">analyze contracts</span>
          </h2>
          <p className="features__subtitle">
            Powered by state-of-the-art NLP models, LexiScan AI transforms the way you review legal documents.
          </p>
        </div>

        <div className="features__grid">
          {features.map((feature, i) => {
            const Icon = feature.icon;
            return (
              <div
                key={feature.title}
                className="features__card glass-card"
                ref={(el) => { cardsRef.current[i] = el; }}
                style={{ animationDelay: `${i * 100}ms` }}
              >
                <div className={`features__icon features__icon--${feature.color}`}>
                  <Icon size={24} />
                </div>
                <h3 className="features__card-title">{feature.title}</h3>
                <p className="features__card-desc">{feature.description}</p>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
