# Local preparation observation — cycle 171

The isolated startup worker launched listeners on 127.0.0.1:8988 (Python PID
75068), 127.0.0.1:8208 (Python PID 75809), and 127.0.0.1:5373 (Node PID 75927).
The coordinator independently observed these using lsof. This establishes only
that the three sockets were listening, not successful API/MCP/browser behavior.

The coordinator bounded the investigation and requested shutdown and a final
receipt. Subsequent lsof confirmed all three ports were clear. HTTP checks
after shutdown failed to connect and provide no acceptance evidence.

No live trial was launched by the coordinator. Authentication, storage, MCP
admission and browser results require the worker's separate receipt before
they can be claimed verified. Local live research acceptance remains open.
