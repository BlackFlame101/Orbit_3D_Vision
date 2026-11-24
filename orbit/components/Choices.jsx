export default function Choices({label,options,value,onChange,disabled=false,segmented=false}){
 return <fieldset className="choices" disabled={disabled} aria-label={label}><legend>{label}</legend>
 <span className={segmented?"segmented":undefined}>{options.map(option=><button type="button" key={option.value} aria-pressed={value===option.value} disabled={option.disabled} onClick={()=>onChange(option.value)}>{option.label??option.value}</button>)}
 </span></fieldset>;
}
