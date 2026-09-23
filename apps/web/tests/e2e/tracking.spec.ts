import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
import AxeBuilder from '@axe-core/playwright';
const env=Object.fromEntries(readFileSync('../../.env','utf8').split(/\r?\n/).filter(l=>l.includes('=')).map(l=>[l.slice(0,l.indexOf('=')),l.slice(l.indexOf('=')+1)]));
test('real login, tracking, comparison, themes and responsive layouts',async({page})=>{
  const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto('/');await page.getByLabel('Email',{exact:true}).fill(env.LOCAL_ADMIN_EMAIL);await page.getByLabel('Password',{exact:true}).fill(env.LOCAL_ADMIN_PASSWORD);await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Create an engineering workspace'}).or(page.getByRole('heading',{name:'Project overview'}))).toBeVisible();
  const post=async(path:string,body:unknown)=>{const r=await page.request.post('http://localhost:8000/api/v1'+path,{data:body,headers:{Origin:'http://localhost:5173'}});expect(r.ok(),await r.text()).toBeTruthy();return r.json()};
  const workspace=await post('/workspaces',{name:'Browser verification',slug:'browser-'+randomUUID().slice(0,8)});
  const project=await post(`/workspaces/${workspace.id}/projects`,{name:'Browser tracking',slug:'tracking'});
  const base=`/w/${workspace.id}/p/${project.id}`;
  await page.goto(base+'/experiments');await page.getByRole('button',{name:'New experiment'}).click();await page.getByRole('dialog').getByLabel('Name',{exact:true}).fill('baseline-models');await page.getByRole('button',{name:'Create experiment',exact:true}).click();await page.getByRole('link',{name:'baseline-models',exact:true}).click();
  const experimentId=page.url().split('/').pop()!;
  for(let index=0;index<2;index++){const run=await post(`/experiments/${experimentId}/runs`,{name:`model-${index}`});await post(`/runs/${run.id}/params:log`,{params:{depth:4+index}}).catch(()=>{});await post(`/runs/${run.id}/metrics:log-batch`,{points:Array.from({length:10},(_,step)=>({id:randomUUID(),key:'loss',value:1/(step+1+index),step,timestamp:new Date().toISOString()}))});await post(`/runs/${run.id}/finish`,{status:'succeeded'});}
  await page.getByRole('button',{name:'Refresh runs'}).click();await expect(page.getByRole('link',{name:'model-0',exact:true})).toBeVisible();await page.getByRole('checkbox',{name:'Select model-0'}).check();await page.getByRole('checkbox',{name:'Select model-1'}).check();await page.getByRole('link',{name:'Compare runs',exact:true}).click();await expect(page.getByRole('heading',{name:'Compare runs'})).toBeVisible();await expect(page.getByText('depth',{exact:true})).toBeVisible();
  await page.goto(base+'/runs?status=succeeded');await page.reload();await expect(page.getByLabel('Run status')).toHaveValue('succeeded');
  for(const width of [1440,768,390]){await page.setViewportSize({width,height:900});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();}
  await page.setViewportSize({width:1440,height:960});await page.goto(base+'/overview');const violations=(await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa','wcag22aa']).analyze()).violations;expect(violations).toEqual([]);
  await page.screenshot({path:'../../docs/screenshots/tracking-dark.png',fullPage:true});await page.getByRole('button',{name:'Toggle color theme'}).click();await page.screenshot({path:'../../docs/screenshots/tracking-light.png',fullPage:true});expect(errors).toEqual([]);
});
