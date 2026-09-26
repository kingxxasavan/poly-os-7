// Every /api/… request lands here (vercel.json rewrites them), so the site uses one function.
import { handle } from '../server/app.js';

export default handle;
