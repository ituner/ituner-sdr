/* Each decoder searches its complete saved history through the shared index. */
(()=>{
 const mode=location.pathname.split('/')[1],nav=document.querySelector('nav');
 if(nav){const a=document.createElement('a');a.href='/search';a.textContent='Search all logs';nav.append(a)}
 if(!['wspr','sstv','hell','qrss','cw'].includes(mode))return;
 const form=document.createElement('form');form.action='/search';form.style.cssText='display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:16px 0;padding:12px;border:1px solid #35515c;border-radius:10px';
 const label=document.createElement('label');label.textContent='Search '+mode.toUpperCase()+' logs ';
 const input=document.createElement('input');input.type='search';input.name='q';input.placeholder='Callsign or part, e.g. S52AB';input.maxLength=80;input.setAttribute('aria-label','Search saved callsigns');label.append(input);
 const hidden=document.createElement('input');hidden.type='hidden';hidden.name='mode';hidden.value=mode;
 const button=document.createElement('button');button.textContent='Search saved history';button.type='submit';
 const all=document.createElement('a');all.href='/search';all.textContent='All decoders';
 form.append(label,hidden,button,all);const header=document.querySelector('header');if(header)header.after(form);else document.body.prepend(form);
})();
