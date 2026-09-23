import { defineConfig } from '@playwright/test';
export default defineConfig({testDir:'./tests/e2e',timeout:60000,workers:1,use:{baseURL:'http://localhost:5173',headless:true,channel:'chrome',trace:'retain-on-failure',screenshot:'only-on-failure'},reporter:'list'});
