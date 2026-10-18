import { useState } from "react";
import type { BoundingBox, Observations, VerificationTarget } from "../../api/generated/contracts";

interface Props {
  image: string;
  observations?: Observations | null;
  targets?: VerificationTarget[];
  modelInput: boolean;
}

function valid(box: BoundingBox): boolean {
  return [box.x_min, box.y_min, box.x_max, box.y_max].every(value => Number.isFinite(value) && value >= 0 && value <= 1000)
    && box.x_max > box.x_min && box.y_max > box.y_min;
}

export function AnnotatedPhoto({ image, observations, targets = [], modelInput }: Props) {
  const [show, setShow] = useState(true);
  const boxes = modelInput ? [
    ...(observations?.targets ?? []).flatMap(item => item.status === "missing" ? [] : (item.boxes ?? []).filter(valid).map(box => ({
      box, label: `${targets.find(target => target.target_id === item.target_id)?.name ?? item.target_id} · ${item.status}`,
      status: item.status,
    }))),
    ...(observations?.unexpected_items ?? []).flatMap(item => (item.boxes ?? []).filter(valid).map(box => ({
      box, label: `${item.name} · unexpected`, status: "unexpected",
    }))),
  ] : [];
  return <>
    <div className="cv-annotated-photo">
      <img src={image} alt="Captured order for this check" />
      {show && boxes.map(({ box, label, status }, index) => <div key={index} className={`cv-object-box cv-object-${status}`} role="img" aria-label={label} style={{
        left: `${box.x_min / 10}%`, top: `${box.y_min / 10}%`, width: `${(box.x_max - box.x_min) / 10}%`, height: `${(box.y_max - box.y_min) / 10}%`,
      }}><span title={label}>{label}</span></div>)}
    </div>
    {!!boxes.length && <label className="cv-box-toggle"><input type="checkbox" checked={show} onChange={event => setShow(event.target.checked)} />Show item boxes ({boxes.length})</label>}
    {observations && !boxes.length && <small>No object locations returned for this photo.</small>}
  </>;
}
