// import Mantissa
// import MochiKit
// import MochiKit.Base
// import MochiKit.Iter
// import MochiKit.DOM

Mantissa.ScrollTable.ScrollModel = Divmod.Class.subclass('Mantissa.ScrollTable.ScrollModel');
Mantissa.ScrollTable.ScrollModel.methods(
    function __init__(self) {
        self._rows = [];
    },

    /**
     * @rtype: integer
     * @return: The number of rows in the model.
     */
    function rowCount(self) {
        return self._rows.length;
    },

    /**
     * Retrieve the index for the row data associated with the given webID.
     *
     * @type webID: string
     *
     * @rtype: integer
     */
    function findIndex(self, webID) {
        for (var i = 0; i < self._rows.length; i++) {
            if (self._rows[i] != undefined && self._rows[i].__id__ == webID) {
                return i;
            }
        }
        throw Error("Specified webID not found.");
    },

    /**
     * Set the data associated with a particular row.
     *
     * @type index: integer
     * @param index: The index of the row for which to set the data.
     *
     * @type data: The data to associate with the row.
     */
    function setRowData(self, index, data) {
        if (index < 0) {
            throw Error("Specified index out of bounds in setRowData.");
        }
        self._rows[index] = data;
    },

    /**
     * Retrieve the row data for the row at the given index.
     *
     * @type index: integer
     *
     * @rtype: object
     * @return: The structured data associated with the row at the given index.
     *
     * @throw Error: Thrown if the given index is out of bounds.
     */
    function getRowData(self, index) {
        if (index < 0 || index >= self._rows.length) {
            throw new Error("Specified index out of bounds in getRowData.");
        }
        if (self._rows[index] === undefined) {
            return undefined;
        }
        return self._rows[index];
    },

    /**
     * Find the row data for the row with web id C{webID}.
     *
     * @type webID: string
     *
     * @rtype: object
     * @return: The structured data associated with the given webID.
     *
     * @throw Error: Thrown if the given webID is not found.
     */
    function findRowData(self, webID) {
        return self.getRowData(self.findIndex(webID));
    },

    /**
     * Find the first row which appears after C{row} in the scrolltable and
     * satisfies C{predicate}
     *
     * @type webID: string
     * @param webID: The web ID of the node at which to begin.
     *
     * @type predicate: function(rowIndex, rowData, rowNode) -> boolean
     * @param predicate: A optional callable which, if supplied, will be called
     * with each row to determine if it suitable to be returned.
     *
     * @rtype: string
     * @return: The web ID for the first set of arguments that satisfies
     * C{predicate}.  C{null} is returned if no rows are found after the given
     * web ID.
     */
    function findNextRow(self, webID, predicate) {
        var row;
        for (var i = self.findIndex(webID) + 1; i < self.rowCount(); ++i) {
            row = self.getRowData(i);
            if (row != undefined) {
                if (!predicate || predicate.call(null, i, row, row.__node__)) {
                    return row.__id__;
                }
            }
        }
        return null;
    },

    /**
     * Same as L{findNextRow}, except returns the first row which appears before C{row}
     */
    function findPrevRow(self, webID, predicate) {
        var row;
        for (var i = self.findIndex(webID) - 1; i > -1; --i) {
            row = self.getRowData(i);
            if (row != undefined) {
                if (!predicate || predicate.call(null, i, row, row.__node__)) {
                    return row.__id__;
                }
            }
        }
        return null;
    },

    /**
     * Remove a particular row from the scrolltable.
     *
     * @type webID: string
     * @param webID: The webID of the row to remove.
     *
     * @return: An object with two properties: C{index}, which refers to the
     * index at which the removed row, and C{row}, which refers to the row data
     * which was removed.
     */
    function removeRow(self, webID) {
        var index = self.findIndex(webID);
        var row = self._rows.splice(index, 1);
        return {index: index, row: row[0]};
    },

    /**
     * Remove all rows from the scrolltable.
     */
    function empty(self) {
        self._rows = [];
    });


Mantissa.ScrollTable.ScrollingWidget = Nevow.Athena.Widget.subclass('Mantissa.ScrollTable.ScrollingWidget');

Mantissa.ScrollTable.ScrollingWidget.methods(
    function __init__(self, node) {
        Mantissa.ScrollTable.ScrollingWidget.upcall(self, '__init__', node);

        self._rowTimeout = null;
        self._requestWaiting = false;
        self._moreAfterRequest = false;

        self.scrollingDown = true;
        self.lastScrollPos = 0;

        self._scrollContent = self.nodeByAttribute("class", "scroll-content");
        self._scrollViewport = self.nodeByAttribute('class', 'scroll-viewport');
        self._headerRow = self.nodeByAttribute('class', 'scroll-header-row');

        self.model = null;
        self.initializationDeferred = self.initialize();
    },


    /**
     * Create a ScrollModel and then populate it with an initial set of rows.
     */
    function initialize(self) {
        /*
         * XXX - Make table metadata into arguments to __init__ to save a
         * round-trip.
         */
        return self.callRemote("getTableMetadata").addCallback(
            function(values) {
                var result = Divmod.objectify(
                    ["columnNames", "columnTypes", "rowCount", "currentSort", "isAscendingNow"],
                    values);

                self.columnTypes = result.columnTypes;

                self._rowHeight = self._getRowHeight();
                self._columnOffsets = self._getColumnOffsets(result.columnNames);

                self._headerNodes = self._createRowHeaders(result.columnNames);
                for (var i = 0; i < self._headerNodes.length; ++i) {
                    self._headerRow.appendChild(self._headerNodes[i]);
                }

                self.setSortInfo(result.currentSort, result.isAscendingNow);
                self.setViewportHeight(result.rowCount);

                self.model = Mantissa.ScrollTable.ScrollModel();

                /*
                 * Grab the initial data set
                 */
                return self._getSomeRows(true);
            });
    },

    /**
     * Retrieve a range of row data from the server.
     *
     * @type firstRow: integer
     * @param firstRow: zero-based index of the first message to retrieve.
     *
     * @type lastRow: integer
     * @param lastRow: zero-based index of the message after the last message
     * to retrieve.
     */
    function getRows(self, firstRow, lastRow) {
        return self.callRemote("requestRowRange", firstRow, lastRow);
    },

    /**
     * Retrieve a range of row data from the server and store it locally.
     *
     * @type firstRow: integer
     * @param firstRow: zero-based index of the first message to retrieve.
     *
     * @type lastRow: integer
     * @param lastRow: zero-based index of the message after the last message
     * to retrieve.
     */
    function requestRowRange(self, firstRow, lastRow) {
        return self.getRows(firstRow, lastRow).addCallback(
            function(rows) {
                var row;
                for (var i = firstRow; i < rows.length + firstRow; ++i) {
                    row = rows[i - firstRow];
                    if (i >= self.model.rowCount() || self.model.getRowData(i) == undefined) {
                        row.__node__ = self._createRow(i, row);
                        self.model.setRowData(i, row);
                        self._scrollContent.appendChild(row.__node__);
                    }
                }
            });
    },

    /**
     * Retrieve a node which is the same height as rows in the table will be.
     */
    function _getRowGuineaPig(self) {
        return MochiKit.DOM.DIV(
            {"style": "visibility: hidden",
             "class": "scroll-row"},
            [MochiKit.DOM.DIV(
                    {"class": "scroll-cell",
                     "style": "float: none"}, "TEST!!!")]);
    },

    /**
     * Determine the height of a row in this scrolltable.
     */
    function _getRowHeight(self) {
        var node = self._getRowGuineaPig();
        var rowHeight;

        /*
         * Put the node into the document so that the browser actually figures
         * out how tall it is.  Don't put it into the scrolltable itself or
         * anything clever like that, in case the scrolltable has some style
         * applied to it that would mess things up. (XXX The body could have a
         * style applied to it that could mess things up? -exarkun)
         */
        document.body.appendChild(node);
        rowHeight = Divmod.Runtime.theRuntime.getElementSize(node).h;
        document.body.removeChild(node);

        if (rowHeight == 0) {
            rowHeight = Divmod.Runtime.theRuntime.getElementSize(self._headerRow).h;
        }

        if (rowHeight == 0) {
            rowHeight = 20;
        }

        return rowHeight;
    },

    /**
     * Set the display height of the scroll view DOM node to a height
     * appropriate for displaying the given number of rows.
     *
     * @type rowCount: integer
     * @param rowCount: The number of rows which should fit into the view node.
     */
    function setViewportHeight(self, rowCount) {
        var scrollContentHeight = self._rowHeight * rowCount;
        self._scrollContent.style.height = scrollContentHeight + 'px';
    },

    /**
     * Increase or decrease the height of the scroll view DOM node by the
     * indicated number of rows.
     *
     * @type rowCount: integer
     * @param rowCount: The number of rows which should fit into the view node.
     */
    function adjustViewportHeight(self, rowCount) {
        var height = parseInt(self._scrollContent.style.height);
        self._scrollContent.style.height = height + (self._rowHeight * rowCount) + "px";
    },

    /**
     * This method is responsible for returning the height of the scroll
     * viewport in pixels.  The result is used to calculate the number of
     * rows needed to fill the screen.
     *
     * Under a variety of conditions (for example, a "display: none" style
     * applied to the viewport node), the browser may not report a height for
     * the viewport.  In this case, fall back to the size of the page.  This
     * will result in too many rows being requested, maybe, which is not very
     * harmful.
     */
    function getScrollViewportHeight(self) {
        var height = Divmod.Runtime.theRuntime.getElementSize(
            self._scrollViewport).h;

        /*
         * Firefox returns 0 for the clientHeight of display: none elements, IE
         * seems to return the height of the element before it was made
         * invisible.  There also seem to be some cases where the height will
         * be 0 even though the element has been added to the DOM and is
         * visible, but the browser hasn't gotten around to sizing it
         * (presumably in a different thread :( :( :() yet.  Default to the
         * full window size for these cases.
         */

        if (height == 0 || isNaN(height)) {
            /*
             * Called too early, just give the page height.  at worst we'll end
             * up requesting 5 extra rows or whatever.
             */
            height = Divmod.Runtime.theRuntime.getPageSize().h;
        }
        return height;
    },

    /**
     * Retrieve some rows from the server which are likely to be useful given
     * the current state of this ScrollingWidget.  Update the ScrollModel when
     * the results arrive.
     *
     * @param scrollingDown: A flag indicating whether we are scrolling down,
     * and so whether the requested rows should be below the current position
     * or not.
     *
     * @return: A Deferred which fires when the update has finished.
     */
    function _getSomeRows(self, scrollingDown) {
        var scrollViewportHeight = self.getScrollViewportHeight();
        var desiredRowCount = Math.ceil(scrollViewportHeight / self._rowHeight);
        var firstRow = Math.floor(self._scrollViewport.scrollTop / self._rowHeight);
        var requestNeeded = false;
        var i;

        /*
         * Never do less than 1 row of work.  The most likely cause of
         * desiredRowCount being 0 is that the browser screwed up some height
         * calculation.  We'll at least try to get 1 row (and maybe we should
         * actually try to get more than that).
         */
        if (desiredRowCount < 1) {
            desiredRowCount = 1;
        }

        if (scrollingDown) {
            for (i = 0; i < desiredRowCount; i++) {
                if (firstRow >= self.model.rowCount() || self.model.getRowData(firstRow) == undefined) {
                    requestNeeded = true;
                    break;
                }
                firstRow++;
            }
        } else {
            for (i = 0; i < desiredRowCount; i++) {
                if (self.model.getRowData(firstRow + desiredRowCount - 1) == undefined) {
                    requestNeeded = true;
                    break;
                }
                firstRow--;
            }
        }

        /* do we have the rows we need ? */

        if (!requestNeeded) {
            return Divmod.Defer.succeed(1);
        }

        return self.requestRowRange(firstRow, firstRow + desiredRowCount);
    },

    /**
     * Convert a Date instance to a human-readable string.
     *
     * @type when: C{Date}
     * @param when: The time to format as a string.
     *
     * @type now: C{Date}
     * @param now: If specified, the date which will be used to determine how
     * much context to provide in the returned string.
     *
     * @rtype: C{String}
     * @return: A string describing the date C{when} with as much information
     * included as is required by context.
     */
    function formatDate(self, date, /* optional */ now) {
        return date.toUTCString();
    },

    /**
     * @param columnName: The name of the column for which this is a value.
     *
     * @param columnType: A string which might indicate the data type of the
     * values in this column (if you have the secret decoder ring).
     *
     * @param columnValue: An object received from the server.
     *
     * @return: The object to put into the DOM for this value.
     */
    function massageColumnValue(self, columnName, columnType, columnValue) {
        var tzoff = (new Date()).getTimezoneOffset() * 60;
        if(columnType == 'timestamp') {
            return self.formatDate(new Date((columnValue - tzoff) * 1000));
        }
	if(columnValue ==  null) {
            return '';
	}
        return columnValue;
    },

    /**
     * Make an element which will be displayed for the value of one column in
     * one row.
     *
     * @param colName: The name of the column for which to make an element.
     *
     * @param rowData: An object received from the server.
     *
     * @return: A DOM node.
     */
    function makeCellElement(self, colName, rowData) {
        var attrs = {"class": "scroll-cell"};
        if(self.columnWidths && colName in self.columnWidths) {
            attrs["style"] = "width:" + self.columnWidths[colName];
        }
        var node = MochiKit.DOM.DIV(
            attrs,
            self.massageColumnValue(
                colName, self.columnTypes[colName][0], rowData[colName]));
        if (self.columnTypes[colName][0] == "fragment") {
            Divmod.Runtime.theRuntime.setNodeContent(node,
                '<div xmlns="http://www.w3.org/1999/xhtml">' + rowData[colName] + '</div>');
        }
        return node;
    },

    /**
     * Override this to set a custom onclick for this action.
     *
     * XXX - Actually, don't override this, because it is going to be removed.
     *
     * XXX - And anyway, how could you have overridden it, none of its
     * parameters are documented.
     */
    function clickEventForAction(self, actionID, rowData) {
    },

    /**
     * Remove all rows from scrolltable, as well as our cache of
     * fetched/unfetched rows, scroll the table to the top, and
     * refill it.
     */
    function emptyAndRefill(self) {
        self._scrollViewport.scrollTop = 0;
        var row;
        for (var i = 0; i < self.model.rowCount(); ++i) {
            row = self.model.getRowData(i);
            if (row != undefined) {
                row.__node__.parentNode.removeChild(row.__node__);
            }
        }
        self.model.empty();
        return self._getSomeRows(true);
    },

    /**
     * Tell the server to change the sort key for this table.
     *
     * @type columnName: string
     * @param columnName: The name of the new column by which to sort.
     */
    function resort(self, columnName) {
        var result = self.callRemote("resort", columnName);
        result.addCallback(function(isAscendingNow) {
                self.setSortInfo(columnName, isAscendingNow);
                self.emptyAndRefill();
            });
        return result;
    },

    /**
     * Tell the server to perform an action on an item.
     *
     * @type actionID: string
     * @param actionID: Which action to perform.
     *
     * @type webID: string
     * @param webID: The webID of the item on which to perform the action.
     */
    function performAction(self, actionID, webID) {
        var result = self.callRemote("performAction", actionID, webID);
        result.addCallback(function(ignored) {
                self.emptyAndRefill();
            });
        return result;
    },

    /**
     * Make a node with some event handlers to perform actions on the row
     * specified by C{rowData}.
     *
     * @param rowData: Some data received from the server.
     *
     * @return: A DOM node.
     */
    function _makeActionsCells(self, rowData) {
        var icon, actionID, onclick, content;
        var actions = [];

        var makeOnClick = function(actionID) {
            return function(event) {
                self.performAction(actionID, rowData["__id__"]);
                return false;
            }
        }
        var actionData = rowData["actions"];
        for(var i = 0; i < actionData.length; i++) {
            icon = actionData[i]["iconURL"];
            actionID = actionData[i]["actionID"];
            onclick = self.clickEventForAction(actionID, rowData);

            if(!onclick) {
                onclick = makeOnClick(actionID);
            }

            if(icon) {
                content = MochiKit.DOM.IMG({"src": icon, "border": 0});
            } else { content = actionID; }

            actions.push(MochiKit.DOM.A({"href": "#",
                                         "onclick": onclick}, content));
        }

        var attrs = {"class": "scroll-cell"};
        if(self.columnWidths && "actions" in self.columnWidths) {
            attrs["style"] = "width:" + self.columnWidths["actions"];
        }
        return MochiKit.DOM.DIV(attrs, actions);
    },

    /**
     * Make a DOM node for the given row.
     *
     * @param rowOffset: The index in the scroll model of the row data being
     * rendered.
     *
     * @param rowData: The row data for which to make an element.
     *
     * @return: A DOM node.
     */
    function _createRow(self, rowOffset, rowData) {
        var cells = [];

        for(var colName in rowData) {
            if(!(colName in self._columnOffsets) || self.skipColumn(colName)) {
                continue;
            }
            if(colName == "actions") {
                cells.push([colName, self._makeActionsCells(rowData)]);
            } else {
                cells.push([colName, self.makeCellElement(colName, rowData)]);
            }
        }

        cells = cells.sort(
            function(data1, data2) {
                var a = self._columnOffsets[data1[0]];
                var b = self._columnOffsets[data2[0]];

                if (a<b) {
                    return -1;
                }
                if (a>b) {
                    return 1;
                }
                return 0;
            });

        var nodes = [];
        for (var i = 0; i < cells.length; ++i) {
            nodes.push(cells[i][1]);
        }
        var rowNode = self.makeRowElement(rowOffset, rowData, nodes);

        rowNode.style.position = "absolute";
        rowNode.style.top = (rowOffset * self._rowHeight) + "px";

        return rowNode;
    },

    /**
     * Create a element to represent the given row data in the scrolling
     * widget.
     *
     * @param rowOffset: The index in the scroll model of the row data being
     * rendered.
     *
     * @param rowData: The row data for which to make an element.
     *
     * @param cells: Array of elements which represent the column data for this
     * row.
     *
     * @return: An element
     */
    function makeRowElement(self, rowOffset, rowData, cells) {
        var attrs = {"class": "scroll-row",
                     "style": "height:" + self._rowHeight + "px"};
        if("actions" in rowData) {
            /* XXX HACK, actions break if the row is clickable */
            return MochiKit.DOM.DIV(attrs, cells);
        }
        return MochiKit.DOM.A(
            {"class": "scroll-row",
             "style": "height:" + self._rowHeight + "px",
             "href": rowData["__id__"]},
            cells);
    },

    /**
     * @param name: column name
     * @return: boolean, indicating whether this column should not be rendered
     */
    function skipColumn(self, name) {
        return false;
    },

    /**
     * Return an object the properties of which are named like columns and
     * refer to those columns' display indices.
     */
    function _getColumnOffsets(self, columnNames) {
        var columnOffsets = {};
        for( var i = 0; i < columnNames.length; i++ ) {
            if(self.skipColumn(columnNames[i])) {
                continue;
            }
            columnOffsets[columnNames[i]] = i;
        }
        return columnOffsets;
    },

    /**
     * Return an Array of nodes to be used as column headers.
     *
     * @param columnNames: An Array of strings naming the columns in this
     * table.
     */
    function _createRowHeaders(self, columnNames) {
        var capitalize = function(s) {
            var words = s.split(/ /);
            var capped = "";
            for(var i = 0; i < words.length; i++) {
                capped += words[i].substr(0, 1).toUpperCase();
                capped += words[i].substr(1, words[i].length) + " ";
            }
            return capped;
        }

        var headerNodes = [];
        var sortable, attrs;
        for (var i = 0; i < columnNames.length; i++ ) {
            if(self.skipColumn(columnNames[i])) {
                continue;
            }

            var columnName = columnNames[i];
            var displayName;

            if(self.columnAliases && columnName in self.columnAliases) {
                displayName = self.columnAliases[columnName];
            } else {
                displayName = capitalize(columnName);
            }

            sortable = self.columnTypes[columnName][1];
            attrs = {"class": "scroll-column-header"};
            if(columnName == "actions") {
                attrs["class"] = "actions-column-header";
            }
            if(self.columnWidths && columnName in self.columnWidths) {
                attrs["style"] = "width:" + self.columnWidths[columnName];
            }
            if(sortable) {
                attrs["class"] = "sortable-" + attrs["class"];
                /*
                 * Bind the current value of columnName instead of just closing
                 * over it, since we're mutating the local variable in a loop.
                 */
                attrs["onclick"] = (function(whichColumn) {
                        return function() {
                            /* XXX real-time feedback, ugh */
                            self.resort(whichColumn);
                        }
                    })(columnName);
            }


            var headerNode = MochiKit.DOM.DIV(attrs, displayName);
            headerNodes.push(headerNode);

        }
        return headerNodes;
    },

    /**
     * Update the view to reflect a new sort state.
     *
     * XXX - This kind of sucks, it should be private, it is an implementation
     * detail.  It should also notice when there are no header nodes at all and
     * do the right thing.
     *
     * @param currentSortColumn: The name of the column by which the scrolling
     * widget's rows are now ordered.
     *
     * @param isAscendingNow: A flag indicating whether the sort is currently
     * ascending.
     *
     */
    function setSortInfo(self, currentSortColumn, isAscendingNow) {
        /*
         * Remove the sort direction arrow from whichever header has it.
         */
        for (var j = 0; j < self._headerNodes.length; j++) {
            while(1 < self._headerNodes[j].childNodes.length) {
                self._headerNodes[j].removeChild(self._headerNodes[j].lastChild);
            }
        }

        /*
         * Put the appropriate sort direction arrow on whichever header
         * corresponds to the new current sort column.
         */
        var c;
        if(isAscendingNow) {
            c = '\u2191'; // up arrow
        } else {
            c = '\u2193'; // down arrow
        }
        self._headerNodes[self._columnOffsets[currentSortColumn]].appendChild(
            MochiKit.DOM.SPAN({"class": "sort-arrow"}, c));
    },

    /**
     * Called in response to only user-initiated scroll events.
     */
    function onScroll(self) {
        var scrollingDown = self.lastScrollPos < self._scrollViewport.scrollTop;
        self.lastScrollPos = self._scrollViewport.scrollTop;
        self.scrolled(undefined, scrollingDown);
    },

    /**
     * Return the number of non-empty rows, ie, rows of which we have a local
     * cache.
     *
     * @rtype: integer
     */
    function nonEmptyRowCount(self) {
        var count = 0;
        for (var i = 0; i < self.model.rowCount(); ++i) {
            if (self.model.getRowData(i) != undefined) {
                ++count;
            }
        }
        return count;
    },

    /**
     * Respond to an event which may have caused to become visible rows for
     * which we do not data locally cached.  Retrieve some data, maybe, if
     * necessary.
     *
     * @type proposedTimeout: integer
     * @param proposedTimeout: The number of milliseconds to wait before
     * requesting data.  Defaults to 250ms.
     *
     * @type scrollingDown: boolean
     * @param scrollingDown: True if the viewport was scrolled down, false
     * otherwise.  Defaults to true.
     */
    function scrolled(self, /* optional */ proposedTimeout, scrollingDown) {
        if (proposedTimeout === undefined) {
            proposedTimeout = 250;
        }
        if(scrollingDown === undefined) {
            scrollingDown = true;
        }
        if (self._requestWaiting) {
            self._moreAfterRequest = true;
            return;
        }
        if (self._rowTimeout !== null) {
            clearTimeout(self._rowTimeout);
        }
        self._rowTimeout = setTimeout(
            function () {
                self._rowTimeout = null;
                self._requestWaiting = true;
                var rowCount = self.nonEmptyRowCount();
                self._getSomeRows(scrollingDown).addBoth(
                    function (rslt) {
                        self._requestWaiting = false;
                        if (self._moreAfterRequest) {
                            self._moreAfterRequest = false;
                            self.scrolled();
                        }
                        self.cbRowsFetched(self.nonEmptyRowCount() - rowCount);
                        return rslt;
                    });
            },
            proposedTimeout);
    },

    /**
     * Callback for some event.  Don't implement this.
     */
    function cbRowsFetched(self) {
    }
    );
