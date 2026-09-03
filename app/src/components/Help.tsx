import { HELP } from '../helpText';

/** ⓘ with a hover/focus tooltip. Unknown ids fail loudly, never blank. */
export default function Help({ id }: { id: string }) {
  const text = HELP[id];
  if (!text) throw new Error(`Help: no help text for id '${id}'`);
  return (
    <span className="help-wrap">
      <button className="help-icon" type="button" aria-label={`About ${id}`}>
        ⓘ
      </button>
      <span className="help-tip" role="tooltip">
        {text}
      </span>
    </span>
  );
}
