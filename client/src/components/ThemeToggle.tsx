import { Monitor, Moon, Sun } from 'lucide-react';
import { useTheme, type ThemeChoice } from '../lib/theme';

const OPTIONS: { value: ThemeChoice; icon: typeof Sun; label: string }[] = [
  { value: 'light', icon: Sun, label: 'Light' },
  { value: 'dark', icon: Moon, label: 'Dark' },
  { value: 'system', icon: Monitor, label: 'System' },
];

export default function ThemeToggle({ withLabels = false }: { withLabels?: boolean }) {
  const { choice, setChoice } = useTheme();
  return (
    <div className="seg" role="radiogroup" aria-label="Theme">
      {OPTIONS.map(({ value, icon: Icon, label }) => (
        <button
          key={value}
          role="radio"
          aria-checked={choice === value}
          className={choice === value ? 'on' : ''}
          onClick={() => setChoice(value)}
          title={label}
          style={withLabels ? undefined : { padding: '0 9px' }}
        >
          <Icon size={14} />
          {withLabels && label}
        </button>
      ))}
    </div>
  );
}
