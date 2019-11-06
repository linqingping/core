"""
Incorporate grpc into python tkinter GUI
"""
import logging
import os
from collections import OrderedDict

from core.api.grpc import client, core_pb2
from coretk.coretocanvas import CoreToCanvasMapping
from coretk.dialogs.sessions import SessionsDialog
from coretk.interface import Interface, InterfaceManager
from coretk.wlannodeconfig import WlanNodeConfig

link_layer_nodes = ["switch", "hub", "wlan", "rj45", "tunnel"]
network_layer_nodes = ["router", "host", "PC", "mdr", "prouter", "OVS"]


class Node:
    def __init__(self, session_id, node_id, node_type, model, x, y, name):
        """
        Create an instance of a node

        :param int session_id: session id
        :param int node_id: node id
        :param core_pb2.NodeType node_type: node type
        :param int x: x coordinate
        :param int y: coordinate
        :param str name: node name
        """
        self.session_id = session_id
        self.node_id = node_id
        self.type = node_type
        self.x = x
        self.y = y
        self.model = model
        self.name = name
        self.interfaces = []


class Edge:
    def __init__(self, session_id, node_id_1, node_type_1, node_id_2, node_type_2):
        """
        Create an instance of an edge
        :param int session_id: session id
        :param int node_id_1: node 1 id
        :param int node_type_1: node 1 type
        :param core_pb2.NodeType node_id_2: node 2 id
        :param core_pb2.NodeType node_type_2: node 2 type
        """
        self.session_id = session_id
        self.id1 = node_id_1
        self.id2 = node_id_2
        self.type1 = node_type_1
        self.type2 = node_type_2
        self.interface_1 = None
        self.interface_2 = None


class CoreServer:
    def __init__(self, name, address, port):
        self.name = name
        self.address = address
        self.port = port


class CoreClient:
    def __init__(self, app):
        """
        Create a CoreGrpc instance
        """
        self.client = client.CoreGrpcClient()
        self.session_id = None
        self.node_ids = []
        self.app = app
        self.master = app.master
        self.interface_helper = None
        self.services = {}

        # distributed server data
        self.servers = {}
        for server_config in self.app.config["servers"]:
            server = CoreServer(
                server_config["name"], server_config["address"], server_config["port"]
            )
            self.servers[server.name] = server

        # data for managing the current session
        self.nodes = {}
        self.edges = {}
        self.hooks = {}
        self.id = 1
        self.reusable = []
        self.preexisting = set()
        self.interfaces_manager = InterfaceManager()
        self.core_mapping = CoreToCanvasMapping()
        self.wlanconfig_management = WlanNodeConfig()

    def handle_events(self, event):
        logging.info("event: %s", event)
        if event.link_event is not None:
            self.app.canvas.wireless_draw.hangle_link_event(event.link_event)

    def handle_throughputs(self, event):
        interface_throughputs = event.interface_throughputs
        for i in interface_throughputs:
            print("")
        return
        throughputs_belong_to_session = []
        for if_tp in interface_throughputs:
            if if_tp.node_id in self.node_ids:
                throughputs_belong_to_session.append(if_tp)
        self.throughput_draw.process_grpc_throughput_event(
            throughputs_belong_to_session
        )

    def join_session(self, session_id):
        # update session and title
        self.session_id = session_id
        self.master.title(f"CORE Session({self.session_id})")

        # clear session data
        self.reusable.clear()
        self.preexisting.clear()
        self.nodes.clear()
        self.edges.clear()
        self.hooks.clear()

        # get session data
        response = self.client.get_session(self.session_id)
        logging.info("joining session(%s): %s", self.session_id, response)
        session = response.session
        self.client.events(self.session_id, self.handle_events)

        # get hooks
        response = self.client.get_hooks(self.session_id)
        logging.info("joined session hooks: %s", response)
        for hook in response.hooks:
            self.hooks[hook.file] = hook

        # determine next node id and reusable nodes
        max_id = 1
        for node in session.nodes:
            if node.id > max_id:
                max_id = node.id
            self.preexisting.add(node.id)
        self.id = max_id
        for i in range(1, self.id):
            if i not in self.preexisting:
                self.reusable.append(i)

        # draw session
        self.app.canvas.canvas_reset_and_redraw(session)

    def create_new_session(self):
        """
        Create a new session

        :return: nothing
        """
        response = self.client.create_session()
        logging.info("created session: %s", response)
        self.join_session(response.session_id)

    def delete_session(self, custom_sid=None):
        if custom_sid is None:
            sid = self.session_id
        else:
            sid = custom_sid
        response = self.client.delete_session(sid)
        logging.info("Deleted session result: %s", response)

    def shutdown_session(self, custom_sid=None):
        if custom_sid is None:
            sid = self.session_id
        else:
            sid = custom_sid
        s = self.client.get_session(sid).session
        # delete links and nodes from running session
        if s.state == core_pb2.SessionState.RUNTIME:
            self.set_session_state("datacollect", sid)
            self.delete_links(sid)
            self.delete_nodes(sid)
        self.delete_session(sid)

    def set_up(self):
        """
        Query sessions, if there exist any, prompt whether to join one

        :return: existing sessions
        """
        self.client.connect()

        # get service information
        response = self.client.get_services()
        for service in response.services:
            group_services = self.services.setdefault(service.group, [])
            group_services.append(service)

        # if there are no sessions, create a new session, else join a session
        response = self.client.get_sessions()
        logging.info("current sessions: %s", response)
        sessions = response.sessions
        if len(sessions) == 0:
            self.create_new_session()
        else:
            dialog = SessionsDialog(self.app, self.app)
            dialog.show()

    def get_session_state(self):
        response = self.client.get_session(self.session_id)
        # logging.info("get session: %s", response)
        return response.session.state

    def set_session_state(self, state, custom_session_id=None):
        """
        Set session state

        :param str state: session state to set
        :return: nothing
        """
        if custom_session_id is None:
            sid = self.session_id
        else:
            sid = custom_session_id

        response = None
        if state == "configuration":
            response = self.client.set_session_state(
                sid, core_pb2.SessionState.CONFIGURATION
            )
        elif state == "instantiation":
            response = self.client.set_session_state(
                sid, core_pb2.SessionState.INSTANTIATION
            )
        elif state == "datacollect":
            response = self.client.set_session_state(
                sid, core_pb2.SessionState.DATACOLLECT
            )
        elif state == "shutdown":
            response = self.client.set_session_state(
                sid, core_pb2.SessionState.SHUTDOWN
            )
        elif state == "runtime":
            response = self.client.set_session_state(sid, core_pb2.SessionState.RUNTIME)
        elif state == "definition":
            response = self.client.set_session_state(
                sid, core_pb2.SessionState.DEFINITION
            )
        elif state == "none":
            response = self.client.set_session_state(sid, core_pb2.SessionState.NONE)
        else:
            logging.error("coregrpc.py: set_session_state: INVALID STATE")

        logging.info("set session state: %s", response)

    def edit_node(self, node_id, x, y):
        position = core_pb2.Position(x=x, y=y)
        response = self.client.edit_node(self.session_id, node_id, position)
        logging.info("updated node id %s: %s", node_id, response)

    def delete_nodes(self, delete_session=None):
        if delete_session is None:
            sid = self.session_id
        else:
            sid = delete_session
        for node in self.client.get_session(sid).session.nodes:
            response = self.client.delete_node(self.session_id, node.id)
            logging.info("delete nodes %s", response)

    def delete_links(self, delete_session=None):
        # sid = None
        if delete_session is None:
            sid = self.session_id
        else:
            sid = delete_session

        for link in self.client.get_session(sid).session.links:
            response = self.client.delete_link(
                self.session_id,
                link.node_one_id,
                link.node_two_id,
                link.interface_one.id,
                link.interface_two.id,
            )
            logging.info("delete links %s", response)

    # TODO add location, hooks, emane_config, etc...
    def start_session(
        self,
        nodes,
        links,
        location=None,
        hooks=None,
        emane_config=None,
        emane_model_configs=None,
        wlan_configs=None,
        mobility_configs=None,
    ):
        response = self.client.start_session(
            self.session_id,
            nodes,
            links,
            hooks=list(self.hooks.values()),
            wlan_configs=wlan_configs,
        )
        logging.debug("Start session %s, result: %s", self.session_id, response.result)

    def stop_session(self):
        response = self.client.stop_session(session_id=self.session_id)
        logging.debug("coregrpc.py Stop session, result: %s", response.result)

    # TODO no need, might get rid of this
    def add_link(self, id1, id2, type1, type2, edge):
        """
        Grpc client request add link

        :param int session_id: session id
        :param int id1: node 1 core id
        :param core_pb2.NodeType type1: node 1 core node type
        :param int id2: node 2 core id
        :param core_pb2.NodeType type2: node 2 core node type
        :return: nothing
        """
        if1 = self.create_interface(type1, edge.interface_1)
        if2 = self.create_interface(type2, edge.interface_2)
        response = self.client.add_link(self.session_id, id1, id2, if1, if2)
        logging.info("created link: %s", response)

    def launch_terminal(self, node_id):
        response = self.client.get_node_terminal(self.session_id, node_id)
        logging.info("get terminal %s", response.terminal)
        os.system("xterm -e %s &" % response.terminal)

    def save_xml(self, file_path):
        """
        Save core session as to an xml file

        :param str file_path: file path that user pick
        :return: nothing
        """
        response = self.client.save_xml(self.session_id, file_path)
        logging.info("coregrpc.py save xml %s", response)
        self.client.events(self.session_id, self.handle_events)

    def open_xml(self, file_path):
        """
        Open core xml

        :param str file_path: file to open
        :return: session id
        """
        response = self.client.open_xml(file_path)
        logging.debug("open xml: %s", response)
        self.join_session(response.session_id)

    def close(self):
        """
        Clean ups when done using grpc

        :return: nothing
        """
        logging.debug("Close grpc")
        self.client.close()

    def peek_id(self):
        """
        Peek the next id to be used

        :return: nothing
        """
        if len(self.reusable) == 0:
            return self.id
        else:
            return self.reusable[0]

    def get_id(self):
        """
        Get the next node id as well as update id status and reusable ids

        :rtype: int
        :return: the next id to be used
        """
        if len(self.reusable) == 0:
            new_id = self.id
            self.id = self.id + 1
            return new_id
        else:
            return self.reusable.pop(0)

    def add_node(self, node_type, model, x, y, name, node_id):
        position = core_pb2.Position(x=x, y=y)
        node = core_pb2.Node(id=node_id, type=node_type, position=position, model=model)
        self.node_ids.append(node_id)
        response = self.client.add_node(self.session_id, node)
        logging.info("created node: %s", response)
        if node_type == core_pb2.NodeType.WIRELESS_LAN:
            d = OrderedDict()
            d["basic_range"] = "275"
            d["bandwidth"] = "54000000"
            d["jitter"] = "0"
            d["delay"] = "20000"
            d["error"] = "0"
            r = self.client.set_wlan_config(self.session_id, node_id, d)
            logging.debug("set wlan config %s", r)
        return response.node_id

    def add_graph_node(self, session_id, canvas_id, x, y, name):
        """
        Add node, with information filled in, to grpc manager

        :param int session_id: session id
        :param int canvas_id: node's canvas id
        :param int x: x coord
        :param int y: y coord
        :param str name: node type
        :return: nothing
        """
        node_type = None
        node_model = None
        if name in link_layer_nodes:
            if name == "switch":
                node_type = core_pb2.NodeType.SWITCH
            elif name == "hub":
                node_type = core_pb2.NodeType.HUB
            elif name == "wlan":
                node_type = core_pb2.NodeType.WIRELESS_LAN
            elif name == "rj45":
                node_type = core_pb2.NodeType.RJ45
            elif name == "tunnel":
                node_type = core_pb2.NodeType.TUNNEL
        elif name in network_layer_nodes:
            node_type = core_pb2.NodeType.DEFAULT
            node_model = name
        else:
            logging.error("grpcmanagemeny.py INVALID node name")
        nid = self.get_id()
        create_node = Node(session_id, nid, node_type, node_model, x, y, name)

        # set default configuration for wireless node
        self.wlanconfig_management.set_default_config(node_type, nid)

        self.nodes[canvas_id] = create_node
        self.core_mapping.map_core_id_to_canvas_id(nid, canvas_id)
        # self.core_id_to_canvas_id[nid] = canvas_id
        logging.debug(
            "Adding node to GrpcManager.. Session id: %s, Coords: (%s, %s), Name: %s",
            session_id,
            x,
            y,
            name,
        )

    def add_preexisting_node(self, canvas_node, session_id, core_node, name):
        """
        Add preexisting nodes to grpc manager

        :param str name: node_type
        :param core_pb2.Node core_node: core node grpc message
        :param coretk.graph.CanvasNode canvas_node: canvas node
        :param int session_id: session id
        :return: nothing
        """

        # update the next available id
        core_id = core_node.id
        if self.id is None or core_id >= self.id:
            self.id = core_id + 1
        self.preexisting.add(core_id)
        n = Node(
            session_id,
            core_id,
            core_node.type,
            core_node.model,
            canvas_node.x_coord,
            canvas_node.y_coord,
            name,
        )
        self.nodes[canvas_node.id] = n

    def update_node_location(self, canvas_id, new_x, new_y):
        """
        update node

        :param int canvas_id: canvas id of that node
        :param int new_x: new x coord
        :param int new_y: new y coord
        :return: nothing
        """
        self.nodes[canvas_id].x = new_x
        self.nodes[canvas_id].y = new_y

    def update_reusable_id(self):
        """
        Update available id for reuse

        :return: nothing
        """
        if len(self.preexisting) > 0:
            for i in range(1, self.id):
                if i not in self.preexisting:
                    self.reusable.append(i)

            self.preexisting.clear()
            logging.debug("Next id: %s, Reusable: %s", self.id, self.reusable)

    def delete_node(self, canvas_id):
        """
        Delete a node from the session

        :param int canvas_id: node's id in the canvas
        :return: thing
        """
        try:
            self.nodes.pop(canvas_id)
            self.reusable.append(canvas_id)
            self.reusable.sort()
        except KeyError:
            logging.error("grpcmanagement.py INVALID NODE CANVAS ID")

    def create_interface(self, node_type, gui_interface):
        """
        create a protobuf interface given the interface object stored by the programmer

        :param core_bp2.NodeType type: node type
        :param coretk.interface.Interface gui_interface: the programmer's interface object
        :rtype: core_bp2.Interface
        :return: protobuf interface object
        """
        if node_type != core_pb2.NodeType.DEFAULT:
            return None
        else:
            interface = core_pb2.Interface(
                id=gui_interface.id,
                name=gui_interface.name,
                mac=gui_interface.mac,
                ip4=gui_interface.ipv4,
                ip4mask=gui_interface.ip4prefix,
            )
            logging.debug("create interface: %s", interface)
            return interface

    def create_edge_interface(self, edge, src_canvas_id, dst_canvas_id):
        """
        Create the interface for the two end of an edge, add a copy to node's interfaces

        :param coretk.grpcmanagement.Edge edge: edge to add interfaces to
        :param int src_canvas_id: canvas id for the source node
        :param int dst_canvas_id: canvas id for the destination node
        :return: nothing
        """
        src_interface = None
        dst_interface = None
        print("create interface")
        self.interfaces_manager.new_subnet()

        src_node = self.nodes[src_canvas_id]
        if src_node.model in network_layer_nodes:
            ifid = len(src_node.interfaces)
            name = "eth" + str(ifid)
            src_interface = Interface(
                name=name, ifid=ifid, ipv4=str(self.interfaces_manager.get_address())
            )
            self.nodes[src_canvas_id].interfaces.append(src_interface)
            logging.debug(
                "Create source interface 1... IP: %s, name: %s",
                src_interface.ipv4,
                src_interface.name,
            )

        dst_node = self.nodes[dst_canvas_id]
        if dst_node.model in network_layer_nodes:
            ifid = len(dst_node.interfaces)
            name = "eth" + str(ifid)
            dst_interface = Interface(
                name=name, ifid=ifid, ipv4=str(self.interfaces_manager.get_address())
            )
            self.nodes[dst_canvas_id].interfaces.append(dst_interface)
            logging.debug(
                "Create destination interface... IP: %s, name: %s",
                dst_interface.ipv4,
                dst_interface.name,
            )

        edge.interface_1 = src_interface
        edge.interface_2 = dst_interface
        return src_interface, dst_interface

    def add_edge(self, session_id, token, canvas_id_1, canvas_id_2):
        """
        Add an edge to grpc manager

        :param int session_id: core session id
        :param tuple(int, int) token: edge's identification in the canvas
        :param int canvas_id_1: canvas id of source node
        :param int canvas_id_2: canvas_id of destination node

        :return: nothing
        """
        if canvas_id_1 in self.nodes and canvas_id_2 in self.nodes:
            edge = Edge(
                session_id,
                self.nodes[canvas_id_1].node_id,
                self.nodes[canvas_id_1].type,
                self.nodes[canvas_id_2].node_id,
                self.nodes[canvas_id_2].type,
            )
            self.edges[token] = edge
            src_interface, dst_interface = self.create_edge_interface(
                edge, canvas_id_1, canvas_id_2
            )
            node_one_id = self.nodes[canvas_id_1].node_id
            node_two_id = self.nodes[canvas_id_2].node_id

            # provide a way to get an edge from a core node and an interface id
            if src_interface is not None:
                self.core_mapping.map_node_and_interface_to_canvas_edge(
                    node_one_id, src_interface.id, token
                )
                logging.debug(
                    "map node id %s, interface_id %s to edge token %s",
                    node_one_id,
                    src_interface.id,
                    token,
                )

            if dst_interface is not None:
                self.core_mapping.map_node_and_interface_to_canvas_edge(
                    node_two_id, dst_interface.id, token
                )
                logging.debug(
                    "map node id %s, interface_id %s to edge token %s",
                    node_two_id,
                    dst_interface.id,
                    token,
                )

            logging.debug("Adding edge to grpc manager...")
        else:
            logging.error("grpcmanagement.py INVALID CANVAS NODE ID")
