odoo.define('mis_report_partner_details.mis_vat_column', [], function (require) {
"use strict";

var $ = window.jQuery;

var _addHeaderColumns = function ($table) {
    if (!$table.length) return;
    
    var $thead = $table.find('thead');
    $thead.find('tr').each(function(rowIndex) {
        var $row = $(this);
        if ($row.find('th.o_mis_kpi_vat_cc').length === 0) {
            var $ths = $row.find('th');
            if ($ths.length >= 1) {
                var $firstTh = $ths.first();
                
                // insert VAT columns
                var $ccTh = $('<th class="o_mis_kpi_vat_cc"></th>');
                var $vatTh = $('<th class="o_mis_kpi_vat"></th>');
                
                var styleAttr = $firstTh.attr('style');
                if (styleAttr) {
                    $ccTh.attr('style', styleAttr);
                    $vatTh.attr('style', styleAttr);
                }
                
                $ccTh.insertAfter($firstTh);
                $vatTh.insertAfter($ccTh);
            }
        }
    });
};

var _processTable = function ($el) {
    try {
        var $table = $el.find('.o_mis_preview table, .o_mis_report_preview table').first();
        if (!$table.length) {
             $table = $el.find('table.mis_builder').first();
        }
        if (!$table.length) { return; }

        _addHeaderColumns($table);

        var $rows = $table.find('tr.o_mis_kpi_row');
        if (!$rows.length) {
            $rows = $table.find('tr').has('td.mis_builder_amount');
        }

        $rows.each(function () {
            var $row = $(this);
            
            if (!$row.hasClass('o_mis_kpi_row')) {
                $row.addClass('o_mis_kpi_row');
            }

            var $descTd = $row.find('td.o_mis_kpi_description').first();
            if (!$descTd.length) { 
                $descTd = $row.find('td').first();
                $descTd.addClass('o_mis_kpi_description');
            }
            if (!$descTd.length) { return; }

            if ($row.find('td.o_mis_kpi_vat_cc').length) { return; }

            var $wrapper = $descTd.find('.o_mis_kpi_line_wrapper');
            var text = $wrapper.length ? $wrapper.text().trim() : $descTd.text().trim();

            var cc = '', num = '', name = text;
            var m = text.match(/^(.*)\s+([A-Za-z]{2})\s+([\d\-\s]+)$/);
            if (m) {
                name = m[1].trim();
                cc = m[2].toUpperCase();
                num = m[3].replace(/\s+/g, ' ').trim();
            }

            if (cc || num) {
                $descTd.empty().text(name);

                var styleAttr = $descTd.attr('style');
                var colorAttr = $descTd.attr('data-color');
                
                var $ccTd = $('<td class="o_mis_kpi_vat_cc"></td>').text(cc);
                var $numTd = $('<td class="o_mis_kpi_vat"></td>').text(num);
                
                if (styleAttr) {
                    $ccTd.attr('style', styleAttr);
                    $numTd.attr('style', styleAttr);
                }
                
                if (colorAttr) {
                    $ccTd.attr('data-color', colorAttr);
                    $numTd.attr('data-color', colorAttr);
                }
                
                $ccTd.insertAfter($descTd);
                $numTd.insertAfter($ccTd);
            } else {
                var styleAttr = $descTd.attr('style');
                var colorAttr = $descTd.attr('data-color');
                
                var $ccTd = $('<td class="o_mis_kpi_vat_cc"></td>');
                var $numTd = $('<td class="o_mis_kpi_vat"></td>');
                
                if (styleAttr) {
                    $ccTd.attr('style', styleAttr);
                    $numTd.attr('style', styleAttr);
                }
                
                if (colorAttr) {
                    $ccTd.attr('data-color', colorAttr);
                    $numTd.attr('data-color', colorAttr);
                }
                
                $ccTd.insertAfter($descTd);
                $numTd.insertAfter($ccTd);
            }
        });
    } catch (e) {
        console.error('MISPartnerVAT error', e);
    }
};

var _ensureColumnConsistency = function ($table) {
    var $thead = $table.find('thead');
    var $tbody = $table.find('tbody');
    
    var headerCols = 0;
    $thead.find('tr').first().find('th').each(function() {
        var colspan = parseInt($(this).attr('colspan')) || 1;
        headerCols += colspan;
    });
    
    var dataCols = $tbody.find('tr').first().find('td').length;
    
    console.log('Header columns:', headerCols, 'Data columns:', dataCols);
};

$(function () {
    var root = $('body');
    _processTable(root);
    _ensureColumnConsistency(root.find('table.mis_builder').first());
    
    var observer = new MutationObserver(function () {
        _processTable(root);
    });
    observer.observe(root[0], { childList: true, subtree: true });
}); // close jQuery ready
}); // close odoo.define