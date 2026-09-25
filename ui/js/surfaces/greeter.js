// PolyOS login screen (LightDM greeter), after the PolyOS 7 Login design.

import { api } from '../api.js';
import { mountAuth } from '../authscreen.js';

export function mount(root, store) {
  mountAuth(root, store, {
    kind: 'login',
    load: () => api.get('/api/greeter/state'),
    signIn: (user, password, session) => api.post('/api/greeter/login', { user, password, session }), // LightDM then starts the desktop
    recover: (user, key, password) => api.post('/api/greeter/recover', { user, key, password }),
    power: (action) => api.post('/api/greeter/power', { action }),
  });
}
